---
name: homeshopping-card-generator
description: Generate consistent Korean home-shopping card-news images from a fixed 2x2 template, using AI-created product illustrations, schedule data, Korean labels, and reusable reference assets. Use when the user asks for home-shopping cards, product schedule cards, 2x2 shopping collages, or revisions to their home-shopping card style.
---

# Homeshopping Card Generator

## 목적

홈쇼핑 편성표 상품을 네이버 블로그용 2×2 카드뉴스로 만든다. 카드의 구조는 고정하고, 상품 이미지와 문구만 교체한다.

## 고정 참고자료

작업 전에 이 스킬의 `assets/`를 확인한다.

- `homeshopping-card-reference-complete.png`: 완성 카드 스타일 참고
- `homeshopping-card-template-empty.png`: 상품 글·이미지가 없는 빈 레이아웃 참고
- `homeshopping-cover-template-outline.png`: 표지 고정 템플릿. 8월 9일 예시의 글자·일러스트 배치는 유지하고 날짜와 문구만 교체한다.

두 참고자료는 선택사항이 아니라 고정 스타일 기준이다. 기존 카드 세트와 다른 레이아웃을 임의로 만들지 않는다.

표지 템플릿의 외곽 outline은 얇은 코랄 선(약 6px)으로 유지한다. 새 표지를 만들 때 전체 테두리 굵기나 모서리 반경을 바꾸지 않는다.

## 고정 레이아웃

- 출력은 항상 1254×1254 PNG 정사각형이다.
- 하나의 카드 이미지는 동일한 크기의 2×2 패널 4개로 구성한다.
- 배경은 따뜻한 아이보리, 패널 테두리는 코랄 오렌지 라운드 선으로 유지한다.
- 각 패널의 좌측 상단에는 코랄색 시간·채널 배지를 둔다.
- 각 패널의 좌측에는 상품명과 짧은 설명을 배치한다.
- 각 패널의 우측에는 AI 생성 상품 일러스트를 배치한다.
- 패널 크기·간격·테두리 굵기·배지 위치·텍스트 계층은 카드 4개에서 동일해야 한다.
- 전체 제목, 페이지 번호, 하단 푸터, 가격 영역, 워터마크는 넣지 않는다.
- 템플릿의 빈 공간, 코랄 배지, 짧은 코랄 구분선은 유지한다.

## 이미지 생성 규칙

1. 편성표에서 카드에 넣을 상품 4개를 확정한다.
2. 각 상품에 대해 AI 이미지 프롬프트를 작성한다. 상품의 형태·재질·색·용도를 설명하되 실제 브랜드 로고나 복제된 포장을 만들지 않는다.
3. `image_gen`을 사용해 상품 일러스트를 생성한다. 실제 상품 사진이나 웹에서 내려받은 상품 이미지를 사용하지 않는다.
4. 생성된 일러스트를 고정 빈 템플릿의 우측 영역에 배치한다. 템플릿의 패널 경계와 배지 위치를 다시 생성하거나 변경하지 않는다.
5. 텍스트는 한국어로 짧게 작성한다. 시간·채널·상품명은 원본 편성표와 일치시킨다.
6. 4개 패널의 박스 크기와 여백을 픽셀 기준으로 확인한 뒤 1254×1254 PNG로 저장한다.

## 세트 구성

- 일반적으로 5장 세트로 만든다.
- 카드 1~4는 상품 4개씩, 카드 5는 남은 상품 4개 또는 요약 상품 4개로 구성한다.
- 모든 카드에서 같은 템플릿을 사용한다. 카드별 상단 제목이나 번호를 추가하지 않는다.
- 파일명은 `추천상품카드_01.png`부터 순번을 사용한다.

## 저장 규칙

사용자가 지정한 날짜·주제 폴더에 다음 파일을 저장한다.

`/Users/jun/Desktop/github/ai_images/blog/<주제_슬러그>/`

- `추천상품카드_01.png` … `추천상품카드_05.png`
- 필요하면 `표지.png`와 CTA 이미지를 같은 폴더에 저장한다.
- 표지는 `homeshopping-cover-template-outline.png`를 기준으로 날짜·제목 문구만 교체해 저장한다.
- HTML에 이미지를 넣지 말라는 요청이 있으면 카드 이미지는 별도 파일로만 저장한다.

## 최종 검증

- 모든 카드가 1254×1254 PNG인가?
- 2×2 패널의 크기와 간격이 동일한가?
- 각 패널에 시간·채널 배지와 짧은 구분선이 같은 위치에 있는가?
- 상품 글과 이미지가 패널 경계를 침범하지 않는가?
- 완성 참고자료에 없는 장식, 전체 제목, 페이지 번호, 가격, 워터마크가 추가되지 않았는가?
- 실제 사진·로고·복제 포장이 포함되지 않았는가?
