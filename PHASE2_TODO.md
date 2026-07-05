# 第2期開発 TODO一覧

第1期(本リポジトリの現状)では以下を実装していません。要件定義書 3.1「MoIP Node機能」および 7章「データ仕様」に記載されている内容のうち、第2期に持ち越したものを一覧化します。

## コンテナ
- `node/` — コンテナ③ Node (Sender/Receiver) の実装。Dockerfile・アプリケーションコード一式。
- `docker-compose.yml` へのコンテナ③追加。

## データ
- `config/sdp_config.json` — SDP内容管理(Sender/Receiver毎の映像・音声パラメータ)。構造は要件定義書 7.5.2 参照。
- `data/sender_logs.db` — Senderログ用DB。
- `data/receiver_logs.db` — Receiverログ用DB。

## 機能
- ST2110準拠のマルチキャストSender/Receiver。
- ST2022-7冗長(Amber/Blue)。
- NMOS IS-04 (Registration API v1.0〜1.3) / IS-05 (Connection Management API v1.0〜1.1) 準拠のふるまい。
- SDPファイルのエクスポート/インポート機能。
- WebRTCによる映像プレビュー、音声バーメーター。

## WebGUI
- dashboard.html: ①-4 Sender①・①-5 Sender②・①-6 Receiver①・①-7 Receiver②ペインの実装(第1期はプレースホルダー表示のみ)。
- settings.html: 「Node」タブ、Sender/Receiver設定タブの追加。

## API
- Sender/Receiverの設定・状態取得API一式(要件定義書 6.2に相当する第2期分)。
- `GET /api/external/sender/status`、`GET /api/external/receiver/status`(要件定義書 7.8.5)。
- NMOS関連エンドポイント(要件定義書 6.3.3)。
