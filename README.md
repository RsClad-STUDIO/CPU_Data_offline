# CPU_Data_offline

CPU情報をローカルに保存し、ネットワーク接続がない環境でも検索できるようにするプロジェクトです。

## 現在の実装

現行版はPython製のCLIアプリケーションです。

- PassMark CPU一覧からCPU名・スコアを取得
- NanoReviewからCPU詳細情報を取得（完全更新時）
- SQLiteにデータを保存
- CPU名の部分一致検索
- Richが利用可能な場合は表形式で表示

## 動作環境

- Python 3.10以上
- Windows / macOS / Linux

これは現在のCLI版の動作環境です。Web/PWA、Android、iOS対応は基盤改修の目標であり、まだ実装済みではありません。

## セットアップ

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

macOS / Linux:

```bash
source .venv/bin/activate
python -m pip install -e .
```

## 起動

```bash
python cpu_lookup.py
python cpu_lookup.py "i7-13700K"
python cpu_lookup.py --fast
python cpu_lookup.py --update
```

パッケージをインストールした場合は、以下のコマンドも利用できます。

```bash
cpu-lookup
cpu-lookup "i7-13700K"
cpu-data-update --fast
cpu-data-update --full
```

## ソース構成

```text
cpu_data/
├─ __init__.py
├─ config.py                      # OS別パス・実行時設定
├─ cli.py                         # CLI表示・入力
├─ database.py                    # 旧package import互換ラッパー
├─ updater.py                     # 旧package import / 起動互換ラッパー
├─ domain/
│  └─ cpu.py                      # CPURecord・データ不変条件
├─ application/
│  └─ update.py                   # 更新ユースケース・チェックポイント
└─ infrastructure/
   ├─ database.py                 # SQLite永続化
   ├─ http.py                     # HTTPセッション・再試行
   └─ sources/
      ├─ errors.py                # データ取得・解析エラー
      ├─ passmark.py              # PassMark取得・解析
      └─ nanoreview.py            # NanoReview取得・正規化

cpu_lookup.py                     # 旧CLI起動パス互換ラッパー
db.py                             # 旧DB import互換ラッパー
updater.py                        # 旧更新 import / 起動パス互換ラッパー
tests/                            # DB・取得パーサー・互換性テスト
```

既存の `python cpu_lookup.py`、`import db`、`import updater` は互換ラッパー経由で維持します。SQLiteファイルの既定位置もプロジェクト直下の `data/cpu.db` のままです。

- 通常起動：対話検索
- `--fast`：PassMark一覧のみを更新
- `--update`：詳細スペックを含めて更新

初回起動時、DBが存在しない場合は高速更新を試みます。

## 設定・データ保存先

既定のSQLiteファイルはプロジェクト直下の `data/cpu.db` です。環境変数 `CPU_DATA_HOME` を指定すると、DBの保存先を任意のディレクトリへ変更できます。複数端末や自作サーバーで保存場所を統一する場合に利用します。

Windows PowerShell:

```powershell
$env:CPU_DATA_HOME = "D:\CPU_Data"
```

macOS / Linux:

```bash
export CPU_DATA_HOME="$HOME/.local/share/cpu-data-offline"
```

その他の調整可能な設定:

| 環境変数 | 既定値 | 用途 |
| --- | ---: | --- |
| `CPU_HTTP_CONNECT_TIMEOUT` | 5 | HTTP接続タイムアウト（秒） |
| `CPU_HTTP_READ_TIMEOUT` | 20 | HTTP読取タイムアウト（秒） |
| `CPU_HTTP_RETRIES` | 3 | GET再試行回数 |
| `CPU_HTTP_RETRY_BACKOFF` | 0.5 | 再試行の待機係数 |
| `CPU_UPDATE_BATCH_SIZE` | 100 | DBへ一括保存する件数 |
| `CPU_NANOREVIEW_DELAY` | 0.5 | NanoReviewへのリクエスト間隔（秒） |

## データ保存先・バックアップ

既定のSQLiteファイルはプロジェクト直下の `data/cpu.db` です。`CPU_DATA_HOME` が設定されている場合はそちらを使用します。

スキーマv2より古い既存DBを初期化・移行する前に、SQLiteのbackup APIで自動バックアップを作成します。ファイル名は `cpu.db.pre-v2-<UTC timestamp>.bak` 形式です。移行後はmetaテーブルの `last_migration_backup` に保存先を記録します。

DB層には `backup_database(destination)` と `verify_database()` を用意しています。バックアップ先に既存ファイルがある場合は上書きせずエラーにします。

## テスト

標準ライブラリのunittestを使用します。

```bash
python -m unittest discover -s tests -v
```

GitHub ActionsではUbuntu / Windows / macOSとPython 3.10 / 3.11 / 3.12の組み合わせでテストします。

## データソース

- [PassMark CPU Benchmarks](https://www.cpubenchmark.net/cpu_list.php)
- [NanoReview CPU](https://nanoreview.net/en/cpu)

取得元のHTML構造や利用条件は変更される可能性があります。外部サイトへのアクセスは更新処理時に発生します。

## 開発方針

当面は新機能を追加せず、既存機能の保全、DB整合性、責務分離、自動テスト、クロスプラットフォーム対応、セルフホスト配備の基盤を優先します。

目標環境:

- Windows / macOS / Linux
- 自作サーバー上のWebアプリ（LAN / Tailscale等のプライベートネットワーク限定）
- Android / iOS（PWAを中心に検討）

設計判断・未解決事項・作業履歴はNotionのプロジェクト技術ナレッジベースで管理します。
