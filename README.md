# CPU_Data_offline

CPU情報をSQLiteへ保存し、ネットワーク接続がない環境でも検索できるPythonアプリケーションです。現在の実装はCLI版です。将来のPC版・NAS版Webアプリに向け、バックエンドを独立したPythonパッケージとして管理します。

## ディレクトリ構成

```text
CPU_Data_offline/
├─ backend/
│  ├─ pyproject.toml
│  ├─ src/cpu_data/
│  │  ├─ domain/             # CPUモデル・メーカー分類
│  │  ├─ application/        # 検索・更新ユースケース
│  │  ├─ infrastructure/    # SQLite・HTTP・外部データソース
│  │  ├─ cli.py              # CLIアダプター
│  │  ├─ config.py           # OS別設定
│  │  └─ database_location.py
│  └─ tests/                 # バックエンドの自動テスト
├─ frontend/                 # 将来のUI（未実装）
├─ deploy/                   # 配備定義（未実装）
├─ docs/                     # 設計・運用ドキュメント
├─ scripts/                  # 保守・診断スクリプト
├─ .gitignore
└─ README.md
```

## 動作環境

- Python 3.10以上
- Windows / macOS / Linux
- SQLite（Python標準ライブラリ）
- 外部データ取得：PassMark、NanoReview

## セットアップ

リポジトリのルートで仮想環境を作成し、バックエンドを編集可能モードでインストールします。

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .\backend
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ./backend
```

## 起動・コマンド

```bash
cpu-lookup
cpu-lookup "i7-13700K"
cpu-lookup search "Ryzen 7" --limit 10 --format json
cpu-lookup show 123
cpu-lookup stats
cpu-lookup db verify
cpu-lookup db backup "./backup/cpu.db"
cpu-lookup update --mode fast
cpu-lookup update --mode full
```

更新専用エントリポイント：

```bash
cpu-data-update --fast
cpu-data-update --full
```

主要サブコマンドは `--format text|json` に対応します。JSONは `schema_version`、`command`、`ok`、`data`、`warnings` を共通フィールドとし、失敗時は `error.code` と `error.message` を返します。更新進捗・診断は標準エラー出力、JSON結果は標準出力に出力します。

終了コードは成功=0、実行時エラー=1、引数エラー=2、show対象なし／曖昧=3、ユーザー中断=130です。更新時のCtrl+Cはキャンセル要求として更新処理へ渡し、処理済みバッチを保存してから終了します。

## データ保存先

既定のSQLiteファイルはOS標準のユーザーデータ領域にある `cpu.db` です。

- Windows: `%LOCALAPPDATA%\CPU_Data_offline\cpu.db`
- macOS: `~/Library/Application Support/CPU_Data_offline/cpu.db`
- Linux: `$XDG_DATA_HOME/cpu-data-offline/cpu.db`（未設定時 `~/.local/share/cpu-data-offline/cpu.db`）

環境変数 `CPU_DATA_HOME` を指定すると、そのディレクトリを最優先で使用します。CLIの `--db-location <ディレクトリ>` でも保存先を指定できます。選択した保存先はユーザー設定に記録されます。

既存DBの保存場所・スキーマ移行処理はアプリケーションコード内に維持されています。今回のソースコード再配置ではDBファイルの移動・変換・更新は行いません。

## 環境変数

| 変数 | 既定値 | 用途 |
| --- | ---: | --- |
| `CPU_DATA_HOME` | OS標準 | DB保存先 |
| `CPU_HTTP_CONNECT_TIMEOUT` | 5 | HTTP接続タイムアウト（秒） |
| `CPU_HTTP_READ_TIMEOUT` | 20 | HTTP読取タイムアウト（秒） |
| `CPU_HTTP_RETRIES` | 3 | GET再試行回数 |
| `CPU_HTTP_RETRY_BACKOFF` | 0.5 | 再試行の待機係数 |
| `CPU_UPDATE_BATCH_SIZE` | 100 | DBへ一括保存する件数 |
| `CPU_NANOREVIEW_DELAY` | 0.5 | NanoReviewへのリクエスト間隔（秒） |

## テスト

リポジトリルートから実行：

```bash
python -m unittest discover -s backend/tests -v
```

またはバックエンドディレクトリから：

```bash
python -m unittest discover -s tests -v
```

テストはローカル環境で実行します。GitHub Actionsは使用しません。

## 保守スクリプト

バックエンドをインストールした状態でリポジトリルートから実行します。

```bash
python scripts/check_database_recovery.py
python scripts/check_live_sources.py
```

## データソース

- [PassMark CPU Benchmarks](https://www.cpubenchmark.net/cpu_list.php)
- [NanoReview CPU](https://nanoreview.net/en/cpu)

取得元のHTML構造や利用条件は変更される可能性があります。外部サイトへのアクセスは更新処理または明示的な診断時に発生します。

## 今後の拡張方針

- `backend/`: CLI・PC版・Web版で共有するアプリケーション基盤
- `frontend/`: 将来のWeb UI。現時点では未実装
- `deploy/`: 将来のNAS / セルフホスト配備定義。現時点では未実装
- `docs/`: アーキテクチャ・運用・開発資料
- `scripts/`: 保守・診断用ツール

PC版はNAS接続を必須としません。NAS版Webアプリはプライベートネットワーク限定で運用する方針です。PC版ローカルDBとNAS版DBの同期方式は未決定です。設計判断・未解決事項・作業履歴はNotionで管理します。
