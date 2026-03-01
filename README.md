# Pixiv API Service

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com)

Pixiv作品情報取得API - Pixiv公式App APIとHTMLスクレイピングの両方に対応したRESTful APIサービス

## ✨ Features

- **🔐 公式API対応**: Pixiv App API (v6.x)を完全サポート
- **🌐 HTMLスクレイピング**: 公式API失敗時の自動フォールバック
- **🚀 高速**: cloudscraper使用でCloudflare回避、非同期処理対応
- **📊 豊富なエンドポイント**: 作品詳細、ランキング、検索、ユーザー情報など
- **🐳 Docker対応**: 簡単デプロイ
- **📝 OpenAPI**: SwaggerUI/ReDocでAPIドキュメント自動生成

## 🆕 What's New

**v2.0.0 - 公式API統合アップデート**

- ✅ [pixivpy](https://github.com/upbit/pixivpy)を参考に公式Pixiv App APIクライアント実装
- ✅ OAuth認証 (refresh_token)サポート
- ✅ 新エンドポイント追加: `/ranking`, `/search`, `/users/{id}`, `/recommended`
- ✅ API優先、失敗時にHTMLスクレイピングへ自動フォールバック
- ✅ 最新Pixiv HTML構造に対応 (2026年2月版)

## 📋 Requirements

- Python 3.9+
- Docker & Docker Compose (推奨)

## 🚀 Quick Start

### Option 1: Docker Compose (推奨)

```bash
# リポジトリクローン
git clone https://github.com/yunfie-twitter/pixapis.git
cd pixapis

# 環境変数設定
cp .env.example .env
vim .env  # PIXIV_REFRESH_TOKEN を設定

# ビルド & 起動
docker-compose up -d

# ログ確認
docker-compose logs -f api
```

### Option 2: ローカル開発

```bash
# 依存関係インストール
pip install -r requirements.txt

# 環境変数設定
export PIXIV_REFRESH_TOKEN="your_refresh_token_here"
export USE_OFFICIAL_API=true

# 開発サーバー起動
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 🔑 Refresh Token の取得方法

公式APIを使用するには`PIXIV_REFRESH_TOKEN`が必要です。

### 方法1: get-pixivpy-token (最も簡単)

```bash
# インストール
pip install get-pixivpy-token

# ログイン
gppt login

# 表示されたrefresh_tokenをコピー
```

詳細: [eggplants/get-pixivpy-token](https://github.com/eggplants/get-pixivpy-token)

### 方法2: 手動取得

1. [OAuth Flow Gist](https://gist.github.com/ZipFile/c9ebedb224406f4f11845ab700124362)の手順に従う
2. Selenium/ChromeDriverでログインフローを実行
3. `refresh_token`を取得

## 📡 API Endpoints

### ヘルスチェック

```bash
GET /health
```

### 作品詳細取得

```bash
# 公式API使用 (デフォルト)
GET /artworks/{artwork_id}

# HTMLスクレイピング強制
GET /artworks/{artwork_id}?force_scraping=true
```

**Response Example:**

```json
{
  "id": 141498782,
  "title": "日野森志歩とドンちゃん",
  "author": {
    "id": 95574061,
    "name": "ゴンず",
    "avatar_url": "https://i.pximg.net/user-profile/img/.../50.jpg"
  },
  "images": [
    {
      "url": "https://i.pximg.net/img-original/img/2026/02/22/20/31/52/141498782_p0.jpg",
      "thumbnail": "https://i.pximg.net/c/250x250_80_a2/...",
      "width": 1443,
      "height": 1457
    }
  ],
  "tags": ["日野森志歩", "レオニード", "プロセカ"],
  "stats": {
    "likes": 12,
    "bookmarks": 20,
    "views": 179
  },
  "created_at": "2026-02-22T11:31:00Z",
  "is_r18": false,
  "page_count": 1,
  "description": "たいたつコラボ嬉しい♡"
}
```

### ランキング取得

```bash
GET /ranking?mode=day&date=2026-03-01
```

**Parameters:**

- `mode`: `day`, `week`, `month`, `day_male`, `day_female`, `week_original`, `week_rookie`, `day_manga`
- `date`: `YYYY-MM-DD` (オプション)
- `offset`: ページネーション用オフセット

### イラスト検索

```bash
GET /search?word=初音ミク&search_target=partial_match_for_tags&sort=popular_desc
```

**Parameters:**

- `word`: 検索キーワード (必須)
- `search_target`: `partial_match_for_tags`, `exact_match_for_tags`, `title_and_caption`
- `sort`: `date_desc`, `date_asc`, `popular_desc`
- `duration`: `within_last_day`, `within_last_week`, `within_last_month`

### ユーザー詳細

```bash
GET /users/{user_id}
```

### ユーザー作品リスト

```bash
GET /users/{user_id}/illusts?type=illust&offset=0
```

### おすすめ作品

```bash
GET /recommended?content_type=illust
```

## 🔧 Configuration

環境変数 (`.env`ファイル):

```bash
# API設定
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4

# Pixiv公式API (推奨)
USE_OFFICIAL_API=true
PIXIV_REFRESH_TOKEN=your_refresh_token_here

# HTMLスクレイピング用 (オプション - R-18作品用)
PIXIV_SESSION=your_phpsessid_cookie

# キャッシュ (オプション)
# REDIS_URL=redis://redis:6379/0
CACHE_TTL=3600

# ログレベル
LOG_LEVEL=INFO
```

## 📚 Documentation

サーバー起動後、以下のURLでAPIドキュメントを確認:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 🏗️ Architecture

```
pixapis/
├── app/
│   ├── main.py              # FastAPIエントリーポイント
│   ├── pixiv_api.py         # 公式Pixiv App APIクライアント (新)
│   ├── scraper.py           # HTMLスクレイパー (フォールバック用)
│   ├── models.py            # Pydanticモデル定義
│   ├── config.py            # 設定管理
│   └── utils.py             # ユーティリティ関数
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## 🔄 Workflow

1. **リクエスト受信** → FastAPI
2. **公式API試行** → `PixivAppAPI` (OAuth認証)
   - ✅ 成功 → レスポンス返却
   - ❌ 失敗 → 次へ
3. **HTMLスクレイピング** → `PixivScraper`
   - JSON抽出 (`meta-preload-data`, `__NEXT_DATA__`)
   - HTMLパース (CSS selectors)
4. **データ変換** → `ArtworkResponse`
5. **レスポンス返却**

## 🛠️ Development

```bash
# 依存関係更新
pip install --upgrade -r requirements.txt

# テスト実行
pytest tests/ -v

# コード品質チェック
flake8 app/
black app/

# Docker再ビルド
docker-compose down
docker-compose up --build
```

## ⚠️ Limitations & Legal

### 技術的制限

- **レート制限**: Pixiv側のレート制限に注意 (キャッシュ推奨)
- **R-18コンテンツ**: 認証必須 (`PIXIV_SESSION` or `PIXIV_REFRESH_TOKEN`)
- **動的コンテンツ**: 一部JavaScriptレンダリングが必要なページは取得不可の場合あり

### 法的考慮事項

- **利用規約準拠**: Pixiv利用規約に違反しない範囲で使用してください
- **個人利用推奨**: 商用利用前にPixiv公式APIの利用を検討してください
- **データ再配布禁止**: 取得データの無断再配布は行わないでください
- **robots.txt**: `/robots.txt`の制限を尊重してください

## 🤝 Contributing

プルリクエスト歓迎!

1. Fork
2. Feature branchを作成 (`git checkout -b feature/amazing`)
3. Commit (`git commit -m 'Add amazing feature'`)
4. Push (`git push origin feature/amazing`)
5. Pull Request作成

## 📝 License

Apache License 2.0 - 詳細は[LICENSE](LICENSE)参照

## 🙏 Acknowledgments

- [upbit/pixivpy](https://github.com/upbit/pixivpy) - 公式API実装の参考
- [Mikubill/pixivpy-async](https://github.com/Mikubill/pixivpy-async) - 非同期実装の参考
- [FastAPI](https://fastapi.tiangolo.com) - 高速Webフレームワーク
- [cloudscraper](https://github.com/VeNoMouS/cloudscraper) - Cloudflare回避

## 📧 Contact

[@yunfie-twitter](https://github.com/yunfie-twitter)

---

**⚡ Powered by FastAPI + Pixiv App API + HTML Scraping**
