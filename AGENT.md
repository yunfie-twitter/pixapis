# AGENT.md - Pixiv API Service

## Project Overview

Pixiv作品情報取得API - Pixivの作品ページから画像URLや作品メタデータを抽出するRESTful APIサービス

**Repository**: [yunfie-twitter/pixapis](https://github.com/yunfie-twitter/pixapis)

## Purpose

Pixiv作品ページ(`https://www.pixiv.net/artworks/{id}`)から以下の情報を抽出:
- フルサイズ画像URL (expand-full-size-illustクラス含む)
- 作品メタデータ(タイトル、タグ、統計情報)
- 投稿者情報
- 関連作品リスト

## Architecture

### Tech Stack
- **FastAPI**: 高速非同期APIフレームワーク
- **httpx**: 非同期HTTPクライアント (Pixivページ取得)
- **BeautifulSoup4 + lxml**: HTMLパーシング
- **Pydantic**: データバリデーション
- **uvicorn**: ASGI Webサーバー
- **Docker**: コンテナ化デプロイ

### Project Structure

```
pixapis/
├── AGENT.md                 # このファイル - AIエージェント向けドキュメント
├── README.md                # ユーザー向けドキュメント
├── LICENSE                  # Apache-2.0ライセンス
├── Dockerfile               # コンテナイメージ定義
├── docker-compose.yml       # Docker Compose設定
├── requirements.txt         # Python依存パッケージ
├── .env.example             # 環境変数テンプレート
├── .dockerignore            # Docker除外ファイル
├── app/
│   ├── main.py              # FastAPIエントリーポイント
│   ├── models.py            # Pydanticモデル定義
│   ├── scraper.py           # Pixivスクレイパーロジック
│   ├── config.py            # 設定管理
│   └── utils.py             # ユーティリティ関数
└── tests/
    ├── test_scraper.py      # スクレイパーテスト
    └── test_api.py          # APIエンドポイントテスト
```

## API Endpoints

### `GET /artworks/{artwork_id}`

作品IDから作品情報を取得

**Parameters**:
- `artwork_id` (path, int): Pixiv作品ID (例: 141733795)

**Response** (200 OK):
```json
{
  "id": 141733795,
  "title": "2/28はビスケットの日!",
  "author": {
    "id": 68480688,
    "name": "妖夢くん",
    "avatar_url": "https://i.pximg.net/user-profile/img/.../50.png"
  },
  "images": [
    {
      "url": "https://i.pximg.net/img-original/img/2026/02/28/17/33/10/141733795_p0.jpg",
      "thumbnail": "https://i.pximg.net/c/250x250_80_a2/img-master/..."
    }
  ],
  "tags": ["東方", "東方Project", "アリス・マーガトロイド"],
  "stats": {
    "likes": 225,
    "bookmarks": 308,
    "views": 2146
  },
  "created_at": "2026-02-28T08:33:00Z",
  "is_r18": false
}
```

**Error Responses**:
- `404`: 作品が存在しない
- `403`: アクセス制限(R-18要認証など)
- `500`: スクレイピング失敗

### `GET /health`

ヘルスチェックエンドポイント

**Response**:
```json
{"status": "ok", "version": "1.0.0"}
```

## Implementation Details

### HTMLスクレイピング戦略

PixivのHTMLからデータ抽出するCSSセレクタ:

```python
# タイトル
title = soup.select_one('h1.sc-965e5f82-3')

# タグ
tags = soup.select('a.gtm-new-work-tag-event-click')

# 統計情報 (いいね、ブックマーク、閲覧数)
stats = soup.select('dl.sc-222c3018-1 dd')

# 投稿日時
time_element = soup.select_one('time[datetime]')

# 投稿者情報
author_link = soup.select_one('a[href^="/users/"]')
author_avatar = soup.select_one('img[alt*="のイラスト"]')

# 画像URL (オリジナルサイズ)
# Note: JavaScriptで動的ロードされる場合はmeta[property="og:image"]をフォールバック
images = soup.select('img.sc-e67f7437-10')
```

### リクエストヘッダー設定

Pixivのbot検出回避:

```python
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://www.pixiv.net/',
    'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
}

# オプション: ログイン済みセッション (R-18作品アクセス用)
if os.getenv('PIXIV_SESSION'):
    cookies = {'PHPSESSID': os.getenv('PIXIV_SESSION')}
```

### キャッシング戦略

Redisまたはインメモリキャッシュで同一作品の重複リクエストを削減:

```python
from functools import lru_cache
from datetime import timedelta

# シンプルなLRUキャッシュ (開発時)
@lru_cache(maxsize=1000)
async def fetch_artwork_cached(artwork_id: int):
    ...

# 本番環境: Redis + TTL 1時間
# await redis.setex(f"artwork:{id}", 3600, json.dumps(data))
```

## Environment Variables

```bash
# API設定
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4

# Pixiv認証 (オプション - R-18作品アクセス用)
PIXIV_SESSION=your_phpsessid_cookie

# キャッシュ設定
REDIS_URL=redis://redis:6379/0  # docker-compose使用時
CACHE_TTL=3600  # 秒

# ログ設定
LOG_LEVEL=INFO
```

## Development Workflow

### ローカル開発

```bash
# 依存関係インストール
pip install -r requirements.txt

# 開発サーバー起動 (ホットリロード有効)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# テスト実行
pytest tests/ -v
```

### Docker開発

```bash
# イメージビルド & 起動
docker-compose up --build

# バックグラウンド起動
docker-compose up -d

# ログ確認
docker-compose logs -f api

# 停止
docker-compose down
```

### APIテスト

```bash
# ヘルスチェック
curl http://localhost:8000/health

# 作品情報取得
curl http://localhost:8000/artworks/141733795

# ドキュメント確認
open http://localhost:8000/docs  # Swagger UI
open http://localhost:8000/redoc # ReDoc
```

## Deployment

### Docker Compose (推奨)

```bash
# 本番環境変数設定
cp .env.example .env
vim .env  # 必要な値を設定

# デプロイ
docker-compose -f docker-compose.yml up -d

# Nginx/Caddy経由でリバースプロキシ設定
```

### Kubernetes (スケーラブルデプロイ)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pixapis
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: api
        image: ghcr.io/yunfie-twitter/pixapis:latest
        ports:
        - containerPort: 8000
        env:
        - name: REDIS_URL
          value: redis://redis-service:6379
```

## Known Limitations

1. **動的コンテンツ**: JavaScriptレンダリングが必要な画像はmeta OGタグからフォールバック取得
2. **レート制限**: Pixiv側のレート制限に注意 (キャッシュで緩和)
3. **R-18コンテンツ**: 未ログイン状態では取得不可 (PHPSESSID要設定)
4. **多ページ作品**: 複数画像の作品は追加リクエストが必要
5. **CAPTCHA**: 過剰リクエストでCAPTCHAが表示される可能性

## Legal Considerations

- **利用規約準拠**: Pixiv利用規約に違反しない範囲で使用
- **個人利用**: 商用利用前にPixiv公式APIの利用を検討
- **Robot.txt**: `/robots.txt`の制限を尊重
- **データ再配布**: 取得データの無断再配布禁止

## Troubleshooting

### よくある問題

**Q: 403 Forbiddenエラーが出る**
→ User-Agentヘッダーが不足 or Pixiv側でIPブロック

**Q: 画像URLが取得できない**
→ JavaScriptレンダリングが必要 → Playwrightへの移行を検討

**Q: R-18作品が取得できない**
→ `PIXIV_SESSION`環境変数にログイン済みCookieを設定

**Q: パフォーマンスが遅い**
→ Redis/Memcachedキャッシュの有効化 & ワーカー数増加

## Future Enhancements

- [ ] Playwright/Seleniumで動的レンダリング対応
- [ ] GraphQL APIでの柔軟なクエリ
- [ ] WebSocket経由のリアルタイム更新
- [ ] ユーザー作品一覧取得エンドポイント
- [ ] ランキング取得API
- [ ] Prometheusメトリクス公開
- [ ] OpenTelemetry分散トレーシング

## Contributing

プルリクエスト歓迎!

1. フォーク
2. フィーチャーブランチ作成 (`git checkout -b feature/amazing`)
3. コミット (`git commit -m 'Add amazing feature'`)
4. プッシュ (`git push origin feature/amazing`)
5. プルリクエスト作成

## License

Apache License 2.0 - 詳細は[LICENSE](LICENSE)参照

## Contact

[@yunfie-twitter](https://github.com/yunfie-twitter)
