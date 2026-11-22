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
.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
```

macOS / Linux:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 起動

```bash
python cpu_lookup.py
python cpu_lookup.py "i7-13700K"
python cpu_lookup.py --fast
python cpu_lookup.py --update
```

- 通常起動：対話検索
- `--fast`：PassMark一覧のみを更新
- `--update`：詳細スペックを含めて更新

初回起動時、DBが存在しない場合は高速更新を試みます。

## データ保存先

既定のSQLiteファイルは `data/cpu.db` です。`db.py` の配置場所を基準に保存します。

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
