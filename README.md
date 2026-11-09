# stt-input (Muse Voice Paste)

Windows 常駐のプッシュ・トゥ・トーク音声入力アプリ。**マウスのサイドボタンを押している間だけ録音し、離すと認識結果を整形して、カーソルの下の入力欄へそのまま入力します。**

チャット、メール、エディタ、ブラウザ——入力欄のある場所ならどこへでも、キーボードに触らず日本語を流し込めます。

## 特徴

- **押している間だけ録音**（プッシュ・トゥ・トーク）。離した瞬間に、離した位置のウィンドウをクリックしてフォーカスし、テキストを入力します
- カーソルに追従する小さなオーバーレイに、録音状態と**ライブ文字起こし**を表示
- 認識は**ローカル実行が基本**。NVIDIA GPU のある PC では faster-whisper、GPU のない PC では Haas-ja の ONNX 版（CPU 実行）を自動で選ぶので、サーバーも WSL も不要です
- 任意で**外部 STT サーバー**にも接続可能。サーバーが落ちている間は自動でローカル認識に切り替わり、その旨をオーバーレイに表示します（黙って切り替わることはありません）
- 整形はルールベースで高速（フィラー除去、音声コマンド、句読点の正規化）。任意で LLM 整形も使えます（既定 OFF）
- **ブラウザの Web エディタでも文字化けしない**よう、入力先に応じてテキストの届け方を自動で切り替えます（後述）

## 動作の流れ

```
[サイドボタンを押す]  録音開始。オーバーレイに 🔴 録音中 + ライブ文字起こし
[話す]               認識結果が伸びていく
[離す]               確定認識 → 整形 → 離した位置をクリック → テキスト入力
```

- 録音中の **Esc** でキャンセル
- 0.35 秒未満の短い押下は誤操作として破棄、録音は上限 120 秒で自動確定
- サイドボタンの本来の動作（ブラウザの「戻る / 進む」）は抑止できます（設定で ON/OFF）

## テキストの入力方式

入力先によって、テキストの届け方を自動で切り替えます（設定 `insert_method: "auto"` が既定）。

| 入力先 | 方式 | 理由 |
|---|---|---|
| ブラウザ（Chrome / Edge / Firefox 等）と Chromium 系アプリ | 文字をウィンドウへ直接届ける（WM_CHAR） | キーイベントとして送ると Chromium の IME 変換経路を通り、Web エディタで文字化け（カタカナ→ひらがな化、漢字の欠落や順序の入れ替わり）が起きるため |
| それ以外（メモ帳、Office、各種エディタ等） | Unicode キーイベントとして打鍵 | クリップボード経由の貼り付け（Ctrl+V）を受け付けないアプリでも確実に入るため |

従来方式の「クリップボード + Ctrl+V」も `insert_method: "paste"` で選択できます。ただしアプリによっては、プログラムから送った Ctrl+V を受け付けないものがあります。

## 認識エンジン

### ローカルエンジンの選択

ローカル認識のエンジンは PC の GPU で決まります（`local_engine: "auto"`）。

| 環境 | ローカルエンジン |
|---|---|
| NVIDIA GPU あり（CUDA で動作） | faster-whisper（下記のモデル自動選択） |
| GPU なし | Haas CPU（Haas-ja の ONNX 版、CPU 実行） |

インストーラーは判定結果を `local_engine` に `"whisper"` / `"haas-cpu"` として書き込みます。手動で切り替えることもできます（設定の「認識」タブ、または `config.json`）。

### Haas CPU（ONNX）

GPU のない PC での既定エンジンです。Hugging Face の [`kizuna-intelligence/Haas-ja-v1.0-OneCompression-ONNX`](https://huggingface.co/kizuna-intelligence/Haas-ja-v1.0-OneCompression-ONNX)（コミュニティによる Haas-ja の ONNX 移植）を `models/haas-onnx/` にダウンロードして使います。

- 形式は `haas_cpu_format` で `int4-onecomp`（既定・最小）/ `int8` / `fp32` から選べます
- このモデルは Python の UTF-8 モードが必要です。アプリは必要な場合に自動で UTF-8 モード（`PYTHONUTF8=1`）で再起動します
- 25 秒を超える発話は自動で分割して認識します

### ローカル認識（faster-whisper）

インストーラーが PC の環境（GPU / VRAM / RAM / CPU スレッド数）を見てモデルを自動選択します（`voice_paste/env_detect.py`）。

| 環境 | モデル | 実行 |
|---|---|---|
| VRAM 10GB 以上 | large-v3-turbo | CUDA float16 |
| VRAM 4.5GB 以上 | large-v3-turbo | CUDA int8_float16 |
| その他の NVIDIA GPU | small | CUDA int8_float16 |
| GPUなし・RAM 16GB 以上・8スレッド以上 | medium | CPU int8 |
| GPUなし・その他 | small | CPU int8 |
| RAM 6GB 未満 | base | CPU int8 |

- GPU ティアでは CUDA ライブラリ（cuBLAS / cuDNN の pip パッケージ）も自動で入ります。実行時に CUDA が使えなかった場合は CPU int8 に自動で落ちるので、音声入力自体が失敗することはありません
- モデルは初回のみ `models/` にダウンロードされます（数百 MB 〜 約 1.6 GB）
- `config.json` の `whisper_model` / `whisper_device` / `whisper_compute` を `"auto"` 以外にすれば手動で固定できます

### 外部 STT サーバー（任意）

次の API を持つ STT サーバーに接続できます（`engine: "haas"`）。

- `GET /health` → `{"ok": true}`
- `POST /transcribe`（音声ファイルのバイト列）→ `{"ok": true, "text": "..."}`
- WebSocket ストリーミング：`{"type": "start", ...}` + PCM16（16 kHz mono）のバイナリ + `{"type": "stop"}` に対し、`partial` / `final` を返す

サーバーの死活は 10 秒間隔で監視し、落ちている間の発話はローカル認識で処理します。接続方式（`stt_transport`）は `auto` / `direct` / `wsl`（WSL 内のサーバーへ `wsl.exe` 経由で届ける経路）から選べます。

### ライブ表示の仕組み

- ローカル認識時：録音中は約 1 秒ごとに「ここまでの音声」を再認識し、LocalAgreement（文字単位）で安定した部分を確定表示します。離した瞬間に全体を高品質設定（beam 5 + VAD）で再認識して確定します。30 秒を超える発話では、再認識コストの都合でライブ表示は止まり経過時間のみ表示されます（確定認識は通常どおり行います）
- サーバー使用時：WebSocket ストリーミングの partial がそのまま表示されます

## インストール

1. Python 3.11+ を用意します
2. `install.bat` を実行します。依存導入 → 環境判定とモデル選択 → モデルの事前ダウンロード → スタートアップ登録まで一括で行います
3. 起動は次回ログインから自動です。手動起動は `run.bat`

### 既存インストールの更新

`update.bat` を実行するだけです（中身は `python tools/update.py`）。GitHub の最新版と比べて、更新があれば起動中のアプリを止め、コードを最新版にそろえ、`setup_env.py` の再実行（環境判定・`local_engine` の書き込み・必要なモデルのダウンロード）まで行い、アプリを再起動します。最新版なら何もしません。

手作業で行う場合の等価な手順は次のとおりです。

1. `git pull` で最新版を取得します
2. `python tools/setup_env.py` を再実行します（他の設定は保持されます）
3. アプリを再起動します（トレイの「終了」→ `run.bat`）

## 整形（formatter）

速さを優先し、既定ではルールベース整形のみ（ネットワーク待ちなし）。

- フィラー除去：文頭・節頭の「えーと / あのー / そのー / えっと / うーん / なんか」
- 音声コマンド：
  - `くてん` → `。`、`とうてん` → `、`（誤変換のない長い形。どこでも有効）
  - `かいぎょう` → 改行、`くうぎょう` → 空行
  - 区切りで独立した `まる` → `。`、`てん` → `、`
  - `aggressive_commands: true` にすると文中の `まる / てん` も変換します（誤変換リスクあり）
- 正規化：`?` → `？`、`!` → `！`、句読点の重複圧縮、日本語間の空白除去、文末の `。` 補完

任意で LLM 整形も可能（`polish_enabled` + OpenAI 互換エンドポイント）。「整形のみ・内容を追加しない」プロンプトで、失敗時はルール整形の結果にフォールバックします。

## 設定

トレイの **「設定...」** から変更できます（3 タブ構成：基本 / 認識 / 整形・貼り付け）。入力は検証され、保存すると `config.json` に書かれます。マイク・トリガー・整形系は即時反映、エンジン系は録音中でなければその場で再構築されます。トレイにはマイクとトリガーのクイック切替もあります。

`config.json` を直接編集しても構いません（雛形は `config.example.json`）。

| キー | 既定 | 意味 |
|---|---|---|
| `engine` | `haas` | `haas`（外部 STT サーバー優先）/ `local`（この PC で認識）。インストーラーがサーバーの有無で自動設定 |
| `fallback_to_local` | `true` | サーバーが落ちていればローカル認識に切替（オーバーレイに明示） |
| `stt_url` | `http://127.0.0.1:8790` | 外部 STT サーバーの URL |
| `stt_transport` | `auto` | `auto` / `direct` / `wsl` |
| `streaming` | `true` | サーバー使用時に WebSocket ストリーミングを使う |
| `local_engine` | `auto` | `auto`（GPU あり→`whisper`、なし→`haas-cpu`）/ `whisper` / `haas-cpu`。インストーラーが具体値を書き込み |
| `haas_cpu_format` | `int4-onecomp` | Haas CPU のモデル形式：`int4-onecomp` / `int8` / `fp32` |
| `haas_cpu_threads` | `4` | Haas CPU の推論スレッド数 |
| `whisper_model` | `auto` | モデル名 or `auto`（環境判定） |
| `whisper_device` | `auto` | `cuda` / `cpu` / `auto` |
| `whisper_compute` | `auto` | `float16` / `int8_float16` / `int8` / `auto` |
| `partial_interval_seconds` | `1.0` | ライブ表示の再認識間隔 |
| `trigger` | `xbutton1` | `xbutton1`（戻る側）/ `xbutton2`（進む側）/ `both` |
| `suppress_trigger` | `true` | サイドボタンの本来の動作を抑止 |
| `min_press_ms` | `350` | これ未満の押下は破棄 |
| `max_seconds` | `120` | 録音上限（秒） |
| `click_to_focus` | `true` | 離した位置のウィンドウをクリックしてから入力 |
| `insert_method` | `auto` | `auto`（入力先で自動選択）/ `type`（打鍵）/ `wmchar`（直接送信）/ `paste`（Ctrl+V） |
| `restore_clipboard` | `true` | `paste` 方式のとき、入力後に元のクリップボードを復元 |
| `mic_name` | `""` | 使うマイクの名前の一部。録音開始ごとに名前で引き直すので、デバイス番号の変動に強い |
| `mic_device` | `null` | マイクのデバイス番号。指定時は `mic_name` より優先（番号は再起動等で変わることがある） |

## プライバシー

- 既定（ローカル認識）では、**音声がこの PC の外に出ることはありません**
- 外部 STT サーバーを使う場合は、自分で用意したサーバー（既定は `127.0.0.1`）に音声が送られます
- LLM 整形を有効にした場合のみ、認識後のテキストが指定したエンドポイントに送られます

## 構成

```
main.py                  エントリ（トレイ常駐）
tools/setup_env.py       環境判定 → モデル選択 → CUDA 導入 → config 書込 → 事前ダウンロード
voice_paste/
  app.py                 状態機械（押下 → 録音 → 確定 → 整形 → 入力）
  local_stt.py           faster-whisper ローカル認識 + LocalAgreement
  haas_cpu_stt.py        Haas-ja ONNX ローカル認識（GPU なしの PC 向け）
  env_detect.py          GPU / VRAM / RAM / CPU 検出とモデル選択
  stt_client.py          外部 STT サーバー用クライアント（任意エンジン）
  formatter.py           整形ルール
  polish.py              任意の LLM 整形
  audio.py               sounddevice 録音（16 kHz mono）
  overlay.py             カーソル追従オーバーレイ（tkinter）
  settings_ui.py         設定ウィンドウ
  win32_input.py         低レベルマウス / キーボードフック、入力方式の自動選択（ctypes のみ）
  config.py              設定
  logutil.py             logs/app.log への記録（pythonw でも失敗が見えるように）
tests/                   単体テスト
models/                  ダウンロードされたモデル（git 管理外）
```

## テスト

```
python -m pytest tests/
```

## 既知の注意

- 入力先の判定は「ボタンを離した位置」で行います。ブラウザのチャット入力欄など、入力欄自体の上で離してください（入力欄の外で離すと、テキストの行き先がありません）
- サイドボタンの抑止はこのアプリが掴んだボタンのみ。他アプリのボタン割り当てと競合する場合は `trigger` を変えてください
- 管理者権限で動くウィンドウへの入力は、このアプリも管理者で起動した場合のみ効きます（Windows の UIPI）
- CPU ティアでは長い発話の確定認識に数秒かかることがあります。GPU ティア（large-v3-turbo）では 10 秒の発話でも 1 秒未満が目安です
- モデルの初回ダウンロードにはネットワークが必要です
