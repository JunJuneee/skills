---
name: google-blog-api-publisher
description: Publish or save an approved Korean blog post package through the Google Blogger API, preserving HTML, labels, publication mode, and card image URLs. Use only when the user explicitly requests Blogger API draft creation or publication.
---

# Google Blogger API Publisher

Publish only an approved post package. Do not create, rewrite, or fact-check the article except to validate the payload.

## Required inputs

- `blog_id`, `title`, `body_html`, and `labels`
- Explicit mode: `draft` or `publish`
- Valid OAuth authorization with `https://www.googleapis.com/auth/blogger`
- Public HTTPS URLs for every image inserted into post HTML

When the user explicitly requests public Blogger publication and supplies local card-news images, upload those images to the configured public image host (Cloudinary when `CLOUDINARY_URL` is available) automatically. Do not ask for a second confirmation about the upload or hosting step. Continue only if upload or URL validation fails; then report the exact prerequisite or error before Blogger mutation.

Never receive API keys, tokens, or secrets in chat. Use a configured connector or environment credentials. Never include local paths or `file://` URLs in HTML.

### Image hosting

- Convert supplied card images to the established JPEG layout before upload when required by the post workflow.
- Upload every body image and any representative image needed for social previews to Cloudinary through its API when `CLOUDINARY_URL` is configured.
- Use only returned public `https://res.cloudinary.com/...` URLs in Blogger HTML; never embed `data:image/...` Base64 or local filesystem paths.
- For a public post, perform the upload as part of the normal publish workflow without asking the user to approve each new image set.
- Verify the expected image count, unique `alt` text, public HTTPS URLs, and the public page's `og:image` before reporting completion.

## OAuth authentication

Use OAuth 2.0 with the Blogger scope `https://www.googleapis.com/auth/blogger`.

### Client secret

- Default credentials directory: `~/.config/lilis-blog/`
- Default client-secret file: `~/.config/lilis-blog/google-client-secret.json`
- Override the client-secret path with `GOOGLE_BLOGGER_CLIENT_SECRET` when needed.
- Read the file only from the local runtime when starting the OAuth flow.
- Never print, upload, commit, or expose its contents.
- If the file is missing or unreadable, stop and report that the client-secret prerequisite is missing.

### First-time authorization

1. Load the OAuth client configuration from `GOOGLE_BLOGGER_CLIENT_SECRET`, or the default client-secret path.
2. Build an authorization URL requesting the Blogger scope and an offline refresh token.
3. Open the URL in the authenticated browser, or return the URL for the user to open.
4. The user signs in to the Google account that owns or can edit the target Blogger blog and approves the Blogger permission.
5. Receive the authorization callback/code through the configured connector; never ask the user to paste a client secret or token into chat.
6. Exchange the code for an access token and refresh token.
7. Store the token set in `~/.config/lilis-blog/blogger-tokens.json` (or `GOOGLE_BLOGGER_TOKEN_PATH`), never in the repository, HTML, logs, or chat.
8. Verify access by reading the target `blog_id` metadata before attempting a post mutation.

### Subsequent runs and reauthentication

- Load the stored refresh token from the configured connector or credential store.
- Refresh the short-lived access token automatically before the Blogger API request when it is expired or near expiry.
- If refresh fails because the token is revoked, expired, or absent, pause before mutation and repeat the first-time authorization flow.
- Do not silently downgrade to an API key; Blogger post creation and publication require OAuth authorization.
- Log only non-sensitive status such as `authorization succeeded`, `token refreshed`, or `reauthorization required`; never log token values, authorization codes, or client-secret contents.

## API sequence

1. Validate target blog, title, HTML, labels, image URLs, and requested mode.
2. Create using `POST https://www.googleapis.com/blogger/v3/blogs/{blogId}/posts` with `title`, `content`, optional `labels`, and `isDraft=true` for a draft.
3. For publish mode, publish the resulting draft with `POST /blogs/{blogId}/posts/{postId}/publish` when required by the available connector.
4. Verify and return response `id`, `url`, title, and final status.

For connector differences, use the official Blogger references: `https://developers.google.com/blogger/docs/3.0/reference/posts/insert` and `https://developers.google.com/blogger/docs/3.0/reference/posts/publish`.

## Safety

- Default to draft if mode is absent or ambiguous.
- Before public publication, require explicit publish instruction and a target `blog_id`.
- If authorization, connector, target blog, or image hosting is missing, stop before mutation and name the missing prerequisite.
- Never update, replace, or delete an existing post unless the user explicitly identifies it and requests that operation.
