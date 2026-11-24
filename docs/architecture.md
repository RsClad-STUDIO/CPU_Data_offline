# Architecture

## Backend layers

`backend/src/cpu_data` は次の責務に分離します。

- `domain`: CPUレコードとドメインルール。外部I/Oに依存しません。
- `application`: 検索・更新ユースケース。UIに依存しません。
- `infrastructure`: SQLite、HTTP、外部データソースの実装。
- `cli.py`: CLI固有の入出力と引数処理。
- `config.py` / `database_location.py`: 実行環境と保存先の構成。

## Dependency direction

CLIなどの将来のUIアダプターはApplicationを呼び出します。ApplicationはDomainとInfrastructureを利用します。Domainは外部レイヤーに依存しません。

## Future components

- `frontend/`: 将来のWeb UI
- `deploy/`: NAS・セルフホスト配備定義
- `scripts/`: 保守・診断スクリプト

未実装領域には実装済みであるかのようなコードや設定を置きません。
