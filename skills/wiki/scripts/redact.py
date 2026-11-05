"""Secret redaction for wiki sources (D15, contract 4). Python 3.9, stdlib only.

Pure functions, no I/O: prepare redacts every source before staging, and
verify reruns scan() over the whole wiki before merging (contract 4).

Replacements are deterministic: a secret always becomes "[REDACTED:<kind>]"
whatever its value, so redacted copies hash the same across runs.

Order of checks:
  1. private key blocks
  2. credentials in URLs (scheme://user:pass@)
  3. known token prefixes (GitHub, Slack, Anthropic, OpenAI, AWS, Google,
     GitLab, Stripe) and JWTs
  4. "Bearer <token>"
  5. assignments (password=..., api_key: ..., *_TOKEN=...)
  6. high entropy (contract 4): [A-Za-z0-9+/=_-]{24,} with Shannon entropy
     >= 4.0, or hex {32,} with entropy >= 3.0

Exceptions (contract 4): 40-char git SHAs, UUIDs, file paths and
redact_allow entries. Implementation detail of the "file path" exception,
recorded as a decision (review rounds 2 and 3: shape alone is not enough,
and a word-like look is no exception by itself; dev:redact_path_rules):

- A candidate without "/" has no exception besides SHA, UUID, redact_allow
  and source ids (below). A natural slug whose entropy reaches 4.0
  (Widget-Orbit-Planner-Example-Quick) is redacted; list it in redact_allow
  if it must stay.
- A candidate with "/" is a path when every segment is path-like. Anchored
  candidates (starting with "/", or inside a whitespace/quote/bracket
  delimited token starting with "/", "~/", "./" or "../"; "~" and "." end
  a candidate, so the part after a dot folder such as ~/.claude/... is its
  own candidate) accept segments whose -_. parts are each word-shaped and
  pronounceable, short hex (git short SHA, UUID pieces, up to 16 digits)
  or at most four alphanumerics. Unanchored candidates need every segment
  to be a word slug (alphabetic-only or digit-only parts). A segment right
  after "projects/" in an anchored path may be a Claude Code project
  folder name (an absolute path with "/" encoded as "-", '-Users-...').
- A page name is no exception by its look either. verify passes the
  wiki's own page file names (24+ chars) as extra allow entries
  (verify.scan_allow), so [[<existing-page>]] stays: that is the file
  path exception, checked against real files instead of inferred.
- A source id inside a src comment ("<!-- src: <kind>:<id> @date -->", kind one of
  mem handoff design prompts inbox manual notes) is a file path by
  construction (ids are built from file names and folder names) and is
  exempt, but only when the caller passes it in known_ids (fix round 1:
  verify passes the batch's SourceIndex ids, scan_tree and prepare the
  sources.json ids). An unknown id in a src-shaped comment is plain text,
  so a comment cannot launder a token into a page, draft or frontmatter.
- Before any path or source-id exemption, the short parts of a candidate
  are checked together (_short_parts_kind, fix round 1): hex parts with a
  digit joined by the hex rule, and what is left once words of five or
  more letters, digit runs and one worktree-suffix hex part per segment
  are cut out by the entropy rule. Dashed or slashed short chunks no
  longer pass as a path. Fix round 2: those words are cut out only when
  their letter pairs read like English on average (an embedded pair
  table), over their segment and over the whole candidate, so random
  letter words (a/Qwerty/Zxcvbn/..., docs/<8>-<8>-<8>) stay in what is
  checked; in a segment of four or more equal-length (4-6) parts,
  digit-only parts stay too (product-key shape ABCD-1234-...). A known
  source id gets the same check before its exemption.
- Any path or source id segment with a part (split on -_.) that is itself
  a 24+ char high-entropy token is still redacted.
- A word-shaped part is lower, UPPER, Capitalized, digits, or case humps
  that each start two or more lowercase letters (GitHub,
  UserProfileSettingsPanel); an alphabetic part of five or more letters
  must also be pronounceable: at least one vowel (a e i o u y), at least
  15% vowels from eight letters on, no run of six or more consonants, and
  no four-letter alphabet run (abcd, dcba).
- Hex joined by "-" (with at least one digit and one letter, 32+ hex
  digits once "-" is removed) is checked by the hex rule.
- redact_allow: a hit is allowed when an entry equals it, contains it (a
  full URL entry covers the span inside it), or, for entries of 8+ chars
  found inside the hit, when what is left once they are cut out holds no
  hit of its own (a bare document id covers the URL span around it).

Emails and internal hosts are not removed; they are only counted as
warnings.
"""

import collections
import math
import re

REDACTED_FMT = "[REDACTED:%s]"
REDACTED_RE = re.compile(r"\[REDACTED:[a-z_]+\]")

ENTROPY_MIN_LEN = 24
ENTROPY_THRESHOLD = 4.0
HEX_MIN_LEN = 32
HEX_ENTROPY_THRESHOLD = 3.0

RedactResult = collections.namedtuple("RedactResult", "text counts warnings")

_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.*?"
    r"(?:-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|\Z)",
    re.DOTALL)
_URL_CRED_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^\s/@:]+):([^\s/@]+)@")

# (kind, regex). The whole match is the secret.
_PREFIX_PATTERNS = (
    ("github", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("slack", re.compile(r"\b(?:xox[abposr]|xapp)-[A-Za-z0-9-]{10,}")),
    ("anthropic", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}")),
    ("openai", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}")),
    ("aws", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("gitlab", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),
    ("stripe", re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
)
_BEARER_RE = re.compile(r"(?i)\b(bearer)(\s+)([A-Za-z0-9._~+/=-]{12,})")
_ASSIGN_KEY = (r"(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key"
               r"|private[_-]?key|client[_-]?secret|credentials?|auth[_-]?key)")
_ASSIGN_RE = re.compile(
    r"(?i)(?P<key>\b[A-Za-z0-9_.-]*" + _ASSIGN_KEY + r"[A-Za-z0-9_.-]*)"
    r"(?P<sep>[\"']?[ \t]*[:=][ \t]*)(?P<q>[\"']?)(?P<val>[^\s\"',;)}\]]{6,})")
_CANDIDATE_RE = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/=_-]{%d,}(?![A-Za-z0-9+/=_-])"
                           % ENTROPY_MIN_LEN)
_HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9A-F]{40}$")
_UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")
_SLUG_PART = r"(?:[A-Za-z]+|[0-9]+)"
_SLUG_RE = re.compile(r"^[-_.]*" + _SLUG_PART + r"(?:[-_.]+" + _SLUG_PART + r")*[-_.]*$")
_SLUG_SPLIT_RE = re.compile(r"[-_.]+")
# A slug part is word-shaped: digits, UPPER, or letters whose case humps
# each start a run of at least two lowercase letters (GitHub,
# UserProfileSettingsPanel, HTTPServerConfig, iOSAppDelegate). Random mixed
# case with one-letter humps (AbCdEfGh) is not.
_WORD_PART_RE = re.compile(r"^(?:[0-9]+|[A-Z]+|[A-Z]*[a-z]+(?:[A-Z]+[a-z]{2,})*[A-Z]*)$")

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_INTERNAL_HOST_RE = re.compile(
    r"(?i)\b(?:[a-z0-9-]+\.)+(?:internal|local|lan|corp|intra|intranet)\b"
    r"|\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b")


def shannon_entropy(value):
    if not value:
        return 0.0
    counts = collections.Counter(value)
    total = float(len(value))
    return -sum((n / total) * math.log(n / total, 2) for n in counts.values())


_VOWELS = frozenset("aeiouy")
_ALPHABET = "abcdefghijklmnopqrstuvwxyz"
_CONSONANT_RUN_RE = re.compile(r"[^aeiouy]{6,}")
# Root folders an encoded absolute path (Claude Code project folder name,
# "/" replaced by "-") can start with.
_ENCODED_ROOTS = frozenset(("users", "home", "opt", "private", "var", "tmp", "volumes",
                            "root", "mnt", "srv", "usr", "workspace", "workspaces", "data"))
_SHORT_HEX_RE = re.compile(r"^(?:[0-9a-f]{1,16}|[0-9A-F]{1,16})$")
_SHORT_ALNUM_RE = re.compile(r"^[A-Za-z0-9]{1,4}$")
_SEGMENT_CHARS_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
# Source kinds of prepare.make_id (src comments cite these ids).
SOURCE_KINDS = ("mem", "handoff", "design", "prompts", "inbox", "manual", "notes")
# Same shape as common.SRC_COMMENT_RE (redact stays import-free).
_SRC_COMMENT_RE = re.compile(r"<!--\s*src:\s*((?:%s):\S+)\s+@\d{4}-\d{2}-\d{2}\s*-->"
                             % "|".join(SOURCE_KINDS))
ALLOW_MIN_SUBSTRING = 8

# Letter-pair scores for _pair_score (fix round 2): row = first letter,
# column = second letter, digit d means log2(P(pair) * 676) ~= d - 5,
# clipped to [-5, 4]. P was counted once, offline, over the letter pairs
# of an English word list and of the words in Python's standard library
# source (identifiers split at case humps); only these 676 digits are
# kept. Random letters average about -1.7 per pair, English words +1.5.
_BIGRAM_ROWS = (
    "47765463615878161878544443",  # a
    "64436100630621520542500030",  # b
    "71437217606632821647621040",  # c
    "63348331710523620553522130",  # d
    "74786653513768564987454641",  # e
    "51235520600512610534501030",  # f
    "51117144600535510542400030",  # g
    "71127100600333610524401050",  # h
    "75876561214769761687360406",  # i
    "30003000101000300000300000",  # j
    "41126121500303210242202020",  # k
    "73458321802733740255531070",  # l
    "75127100701343660143500040",  # m
    "73778573724435742378542041",  # n
    "45664463504778671866755422",  # o
    "71227216601612650755502050",  # p
    "00000000000000000010500000",  # q
    "84558453804565840566543060",  # r
    "62637336704554663378613050",  # s
    "72538417801543740766623162",  # t
    "55545440501667350676110100",  # u
    "50007000500010400000100000",  # v
    "51125104500203400431001100",  # w
    "32324201400120240015100330",  # x
    "32434121300444350354002121",  # y
    "40005000300000300000000013",  # z
)
# Mean pair score the words of the whole candidate, and of a segment with
# at least SEGMENT_MIN_PAIRS letter pairs in its words, must reach before
# they are cut out as words (_short_parts_kind). A segment with fewer pairs
# (one short word such as "keyword") is too little evidence on its own.
WORDS_MIN_PAIR_SCORE = 0.0
SEGMENT_MIN_PAIRS = 10


def _pronounceable(part):
    """False for alphabetic parts that do not read like a word (see the
    module docstring). Digits and parts under five letters pass."""
    if len(part) < 5 or not part.isalpha():
        return True
    low = part.lower()
    for index in range(len(low) - 3):
        chunk = low[index:index + 4]
        if chunk in _ALPHABET or chunk[::-1] in _ALPHABET:
            return False
    if _CONSONANT_RUN_RE.search(low):
        return False
    vowels = sum(1 for ch in low if ch in _VOWELS)
    if not vowels:
        return False
    return len(low) < 8 or vowels >= 0.15 * len(low)


def _word_part(part):
    return bool(_WORD_PART_RE.match(part)) and _pronounceable(part)


def _pair_score(part):
    """(sum, count) of the _BIGRAM_ROWS scores of an alphabetic part's
    letter pairs, case ignored."""
    low = part.lower()
    total = 0
    count = 0
    for first, second in zip(low, low[1:]):
        if "a" <= first <= "z" and "a" <= second <= "z":
            total += int(_BIGRAM_ROWS[ord(first) - 97][ord(second) - 97]) - 5
            count += 1
    return total, count


def _word_slug(value):
    """A slug whose every -_. part is word-shaped and pronounceable."""
    if not _SLUG_RE.match(value):
        return False
    return all(_word_part(part) for part in _SLUG_SPLIT_RE.split(value) if part)


def _path_part(part):
    return _word_part(part) or bool(_SHORT_HEX_RE.match(part)) or bool(_SHORT_ALNUM_RE.match(part))


def _path_segment(segment):
    """An anchored path segment: every -_. part word-like, short hex or
    short alphanumeric (file names, worktree names with a short hash)."""
    if not _SEGMENT_CHARS_RE.match(segment):
        return False
    parts = [part for part in _SLUG_SPLIT_RE.split(segment) if part]
    return bool(parts) and all(_path_part(part) for part in parts)


def _encoded_absolute(segment):
    """'-Users-someone-...' style: an absolute path with '/' encoded as '-'."""
    if not segment.startswith("-"):
        return False
    parts = [part for part in segment.split("-") if part]
    return len(parts) >= 2 and parts[0].lower() in _ENCODED_ROOTS


def _segment_is_secret(segment):
    """A path segment is secret when one of its -_. separated parts is a
    24+ char high-entropy token (so worktree names with a short hash stay)."""
    for part in _SLUG_SPLIT_RE.split(segment):
        if len(part) >= ENTROPY_MIN_LEN and _candidate_kind(part, allow_paths=False) is not None:
            return True
    return False


def has_secret_part(value):
    """True when a -_./ separated part of value is a 24+ char high-entropy
    token (used by verify before trusting a page file name)."""
    return any(_segment_is_secret(segment) for segment in value.split("/") if segment)


_TOKEN_STOPS = frozenset(" \t\r\n`\"'([{<>|,;")


def _token_start(text, start):
    """Start of the token around text[start] (back to whitespace, a quote
    or a bracket)."""
    index = start
    while index > 0 and text[index - 1] not in _TOKEN_STOPS:
        index -= 1
    return index


def _token_anchored(text, start):
    """True when the token around text[start] starts like an absolute or
    relative path."""
    return text.startswith(("/", "~/", "./", "../"), _token_start(text, start))


def _src_spans(text):
    """(start, end, id) of every source id cited in a src comment of text."""
    return [match.span(1) + (match.group(1),) for match in _SRC_COMMENT_RE.finditer(text)]


_SLUG_KEEP_RE = re.compile(r"([-_.]+)")
_SEP_RUN_RE = re.compile(r"[-_.]{2,}")
_SUFFIX_HEX_RE = re.compile(r"^(?:[0-9a-f]{6,16}|[0-9A-F]{6,16})$")
_EMBEDDED_ID_RE = re.compile(
    r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
    r"|[0-9a-f]{40}|[0-9A-F]{40})(?![0-9A-Fa-f])")
# macOS per-user temp folder, plain (var/folders/xx/<id>/T) or encoded in a
# Claude Code project folder name (-var-folders-xx-<id>-T-..., the "_" in
# the id encoded as "-"): a file path by construction, cut out like UUIDs
# before the short-parts check (fix round 2, now that a known source id
# gets that check too). The id is two alphanumeric runs joined by one "_"
# or "-", so a run of dashed short chunks in that slot is not cut.
_DARWIN_TMP_RE = re.compile(
    r"(?<![A-Za-z0-9])var[-/]folders[-/][0-9a-z_]{2}[-/][0-9a-z]{6,24}[-_][0-9a-z]{6,24}"
    r"[-/][CTX](?![A-Za-z0-9])")


def _short_parts_kind(value):
    """Kind ("hex" or "entropy") when the short parts of value carry a
    secret together, else None (fix round 1). Runs on every candidate
    before any path or source-id exemption.

    - Per segment, the last 6-16 digit hex part with a digit is the
      worktree-suffix (or short SHA) shape. All hex parts with a digit
      joined are checked by the hex rule (32+ digits, entropy >= 3.0), so
      /a/<16 hex>/<16 hex> and <16 hex>-<16 hex> are caught.
    - The candidate with its words of five or more letters, its digit runs
      and those suffixes cut out (separators kept) is checked by the
      entropy rule (24+ chars, entropy >= 4.0; the whole candidate must
      reach 4.0 too, so cutting words out never makes a hit). Dashed short chunks
      (Kq7Z-p2Wm-..., ab-cd-ef-..., /srv/Kq7Z/p2Wm/...) are caught;
      natural names keep their long words out of it.
    - Fix round 2: the words are cut out only when their letter pairs read
      like English on average (_pair_score mean >= WORDS_MIN_PAIR_SCORE),
      over the whole candidate and over their own segment when it holds
      SEGMENT_MIN_PAIRS letter pairs or more. Random
      letter words (a/Qwerty/Zxcvbn/..., docs/<8>-<8>-<8>) then stay in
      what is checked; natural names, which may hold a few odd words
      among ordinary ones, keep theirs out. In a segment of four or more
      parts of one length (4-6), digit-only parts stay too (product-key
      shape ABCD-1234-...).
    UUIDs and 40-char SHAs (contract-4 exceptions) and the macOS per-user
    temp folder (_DARWIN_TMP_RE) are cut out first."""
    hex_parts = []
    segments = []
    all_sum = all_count = 0
    value = _DARWIN_TMP_RE.sub("var-", value)
    for segment in value.split("/"):
        segment = _EMBEDDED_ID_RE.sub("-", segment)
        pieces = _SLUG_KEEP_RE.split(segment)
        suffix = None
        for index in range(len(pieces) - 1, -1, -1):
            if _SUFFIX_HEX_RE.match(pieces[index]) and re.search(r"[0-9]", pieces[index]):
                suffix = index
                break
        parts = [piece for piece in pieces if piece and not _SLUG_SPLIT_RE.match(piece)]
        keyish = len(parts) >= 4 and len(set(len(part) for part in parts)) == 1 and (
            4 <= len(parts[0]) <= 6)
        kinds = []
        seg_sum = seg_count = 0
        for index, piece in enumerate(pieces):
            if not piece or _SLUG_SPLIT_RE.match(piece):
                kinds.append("sep")
                continue
            is_hex = bool(_HEX_RE.match(piece) and re.search(r"[0-9]", piece)
                          and not piece.isdigit())
            if is_hex:
                hex_parts.append(piece)
            if index == suffix or (piece.isdigit() and not keyish):
                kinds.append("cut")
            elif len(piece) >= 5 and not is_hex and not piece.isdigit() and _word_part(piece):
                kinds.append("word")
                score, count = _pair_score(piece)
                seg_sum += score
                seg_count += count
            else:
                kinds.append("keep")
        all_sum += seg_sum
        all_count += seg_count
        segments.append((pieces, kinds, seg_sum, seg_count))
    words_ok = all_sum >= WORDS_MIN_PAIR_SCORE * all_count
    weak = []
    for pieces, kinds, seg_sum, seg_count in segments:
        cut_words = words_ok and (seg_count < SEGMENT_MIN_PAIRS
                                  or seg_sum >= WORDS_MIN_PAIR_SCORE * seg_count)
        out = []
        for piece, kind in zip(pieces, kinds):
            if kind == "cut" or (kind == "word" and cut_words):
                out.append("")
            else:
                out.append(piece)
        weak.append(_SEP_RUN_RE.sub(lambda m: m.group(0)[0], "".join(out)).strip("-_."))
    joined_hex = "".join(hex_parts)
    if (len(joined_hex) >= HEX_MIN_LEN and _HEX_RE.match(joined_hex)
            and shannon_entropy(joined_hex) >= HEX_ENTROPY_THRESHOLD):
        return "hex"
    joined = "/".join(part for part in weak if part)
    if (len(joined) >= ENTROPY_MIN_LEN and shannon_entropy(joined) >= ENTROPY_THRESHOLD
            and shannon_entropy(value) >= ENTROPY_THRESHOLD):
        return "entropy"
    return None


def _is_path(value, anchored=False):
    if "/" not in value:
        return False
    segments = [segment for segment in value.split("/") if segment]
    if not segments:
        return True
    if any(_segment_is_secret(segment) for segment in segments):
        return False
    if anchored or value.startswith("/"):
        for index, segment in enumerate(segments):
            if _path_segment(segment):
                continue
            if index > 0 and segments[index - 1] == "projects" and _encoded_absolute(segment):
                continue
            return False
        return True
    return all(_word_slug(segment) for segment in segments)


def _dashed_hex(value):
    stripped = value.replace("-", "")
    return (stripped != value and len(stripped) >= HEX_MIN_LEN and _HEX_RE.match(stripped)
            and re.search(r"[0-9]", stripped) and re.search(r"[A-Fa-f]", stripped))


def _candidate_kind(value, allow_paths=True, anchored=False, source_id=False):
    """Kind of a high-entropy candidate, or None when it is not a secret."""
    if _SHA40_RE.match(value) or _UUID_RE.match(value):
        return None
    if _dashed_hex(value):
        return "hex" if shannon_entropy(value.replace("-", "")) >= HEX_ENTROPY_THRESHOLD else None
    # Before every exemption, the source-id one included (fix round 2: a
    # known id is no way around the short-parts check either).
    short_kind = _short_parts_kind(value)
    if short_kind is not None:
        return short_kind
    if allow_paths and source_id and not any(
            _segment_is_secret(segment) for segment in value.split("/") if segment):
        # Only reached for an id the caller checked (redact known_ids): it
        # was built from real file and folder names, so past the checks
        # above only a 24+ char token part counts.
        return None
    if allow_paths and _is_path(value, anchored):
        return None
    if len(value) >= HEX_MIN_LEN and _HEX_RE.match(value):
        if shannon_entropy(value) >= HEX_ENTROPY_THRESHOLD:
            return "hex"
        return None
    if shannon_entropy(value) >= ENTROPY_THRESHOLD:
        return "entropy"
    return None


def _placeholder(value):
    stripped = value.strip()
    if not stripped:
        return True
    if stripped[0] in "$<{%[*" or stripped.startswith("REDACTED"):
        return True
    if len(set(stripped)) == 1:
        return True
    return stripped.lower() in ("xxxxxx", "changeme", "example", "redacted", "none", "null")


def redact(text, allow=(), known_ids=None):
    """Return RedactResult(text, counts, warnings) for one source text.

    known_ids: source ids a caller has checked (sources.json, this batch).
    Only an id in a src comment that is one of them gets the source-id
    exemption (fix round 1); without known_ids no src-shaped span is
    exempt, so a src comment cannot launder a token."""
    known = frozenset(known_ids or ())
    allow_set = set(item for item in (allow or ()) if isinstance(item, str) and item)
    long_allow = sorted((item for item in allow_set if len(item) >= ALLOW_MIN_SUBSTRING),
                        key=len, reverse=True)
    counts = collections.Counter()

    def allowed(value):
        """An entry equals value or contains it (a full URL entry)."""
        return value in allow_set or any(value in item for item in allow_set)

    def sub_whole(kind):
        def repl(match):
            if allowed(match.group(0)):
                return match.group(0)
            counts[kind] += 1
            return REDACTED_FMT % kind
        return repl

    text = _PRIVATE_KEY_RE.sub(sub_whole("private_key"), text)

    def url_repl(match):
        cred = "%s:%s" % (match.group(2), match.group(3))
        if allowed(cred) or allowed(match.group(3)) or _placeholder(match.group(3)):
            return match.group(0)
        counts["url_cred"] += 1
        return match.group(1) + (REDACTED_FMT % "url_cred") + "@"

    text = _URL_CRED_RE.sub(url_repl, text)
    for kind, pattern in _PREFIX_PATTERNS:
        text = pattern.sub(sub_whole(kind), text)

    def bearer_repl(match):
        token = match.group(3)
        if allowed(token) or REDACTED_RE.search(token):
            return match.group(0)
        counts["bearer"] += 1
        return match.group(1) + match.group(2) + (REDACTED_FMT % "bearer")

    text = _BEARER_RE.sub(bearer_repl, text)

    def assign_repl(match):
        value = match.group("val")
        if allowed(value) or _placeholder(value) or REDACTED_RE.match(value):
            return match.group(0)
        counts["assign"] += 1
        return match.group("key") + match.group("sep") + match.group("q") + (REDACTED_FMT % "assign")

    text = _ASSIGN_RE.sub(assign_repl, text)

    def entropy_repl(match):
        value = match.group(0)
        if allowed(value):
            return value
        anchored = _token_anchored(match.string, match.start())
        start = match.start()
        in_src = any(low <= start and match.end() <= high and cited in known
                     for low, high, cited in src_spans)
        kind = _candidate_kind(value, anchored=anchored, source_id=in_src)
        if kind is None:
            return value
        if _covered_by_allow(value, anchored):
            return value
        counts[kind] += 1
        return REDACTED_FMT % kind

    def _covered_by_allow(value, anchored):
        """Entries of 8+ chars found inside value (a bare document id inside
        a URL span) cover it when what is left holds no hit of its own."""
        inside = [item for item in long_allow if item in value]
        if not inside:
            return False
        rest = value
        for item in inside:
            rest = rest.replace(item, " ")
        for piece in _CANDIDATE_RE.finditer(rest):
            if _candidate_kind(piece.group(0), anchored=anchored) is not None:
                return False
        return True

    src_spans = _src_spans(text) if known else []
    text = _CANDIDATE_RE.sub(entropy_repl, text)

    warnings = collections.Counter()
    for match in _EMAIL_RE.finditer(text):
        if not allowed(match.group(0)):
            warnings["email"] += 1
    for match in _INTERNAL_HOST_RE.finditer(text):
        if not allowed(match.group(0)):
            warnings["internal_host"] += 1
    return RedactResult(text, dict(counts), dict(warnings))


def scan(text, allow=(), known_ids=None):
    """Secret kinds still present in text ({} when clean). Used by verify."""
    return redact(text, allow, known_ids).counts
