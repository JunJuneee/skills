---
name: homeshopping-supabase-import
description: Upload HomeShopick/Home Shopping Moa representative-schedule Excel files into the production Supabase database with date validation, duplicate-day protection, channel validation, batched inserts, and post-upload row verification. Use when the user asks to add, import, upload, or backfill Korean home-shopping schedule spreadsheets into HomeShopick.
---

# HomeShopick 편성 업로드

HomeShopick의 대표상품 편성표 `.xlsx` 파일을 기존 Supabase 스키마에 안전하게 등록한다. 업로드는 사용자가 명시적으로 요청한 경우에만 실행하고, 같은 날짜가 이미 등록되어 있으면 중복 업로드를 시도하지 않는다.

## Workflow

1. 파일 경로를 확인한다.
   - 파일이 실제로 존재하는지 확인한다.
   - 파일명 날짜와 시트의 `방송시작` 날짜가 일치하는지 확인한다.
   - 여러 파일을 받으면 날짜순으로 정렬한다.
2. 기존 importer를 재사용한다.

   ```text
   /Users/jun/Desktop/ontime-shop-preview/scripts/import-representative-schedule.mjs
   ```

   실행 환경에는 `SUPER_BASE_KEY`가 있어야 한다. 키를 출력하거나 파일에 기록하지 않는다. 기본 Supabase URL은 importer에 설정된 HomeShopick 프로젝트를 사용한다.

3. 날짜별로 한 파일씩 순차 실행한다.

   ```bash
   node /Users/jun/Desktop/ontime-shop-preview/scripts/import-representative-schedule.mjs \
     "/absolute/path/홈쇼핑모아_YYYY-MM-DD_대표상품.xlsx"
   ```

4. 각 실행 결과를 확인한다.
   - `Imported YYYY-MM-DD: products N, broadcasts M` 출력이 있어야 성공이다.
   - 이미 해당 날짜의 방송이 있으면 importer가 중복을 차단하므로, 그 날짜는 건너뛰고 사용자에게 알린다.
   - 존재하지 않는 채널, 여러 날짜가 섞인 파일, 빈 파일, Supabase 오류가 있으면 다음 날짜를 무리하게 진행하지 말고 원인과 대상 파일을 보고한다.
5. 최종 결과에 날짜별 상품 수·방송 수와 건너뛴 날짜·실패 원인을 요약한다.

## Safety and data rules

- 업로드는 DB를 변경하므로 사용자의 명시적 요청 없이 실행하지 않는다.
- 기존 날짜 데이터를 삭제·덮어쓰기하지 않는다. 재수집이 필요하면 먼저 사용자에게 기존 데이터 정리 여부를 확인한다.
- importer가 수행하는 날짜 중복 검사와 업로드 후 방송 건수 검증을 우회하지 않는다.
- `SUPER_BASE_KEY`나 Supabase 응답의 인증 정보는 최종 답변·로그·Discord 메시지에 포함하지 않는다.
- 엑셀 원본은 수정하지 않는다.

## Reporting format

```text
Supabase 업로드 완료
- YYYY-MM-DD: 상품 N개, 방송 M건
- YYYY-MM-DD: 중복으로 건너뜀
- YYYY-MM-DD: 실패 — 원인
검증: 업로드 후 방송 건수 확인 완료
```
