#!/usr/bin/env python3
from flask import Flask, request, jsonify, Response, render_template
import anthropic
import json
import math

app = Flask(__name__)

BATCH_SIZE = 5

SYSTEM_PROMPT = """あなたはLovegraph（ラブグラフ）の写真品質審査員です。
カップルフォトの品質を厳密に評価してください。
JSON以外の出力は不要です。必ずJSONのみを返してください。"""

def build_batch_prompt(batch_start, batch_end, total):
    return f"""写真 {batch_start}〜{batch_end}枚目（全{total}枚中）を評価してください。

## 評価基準

### 【最重要】肌色・レタッチ
特に「顔全体の色の統一感」を最も厳しくチェックしてください。

1. 顔の色の統一感（最重要）
   - 顔の明るい部分と影の部分で色味が一貫しているか
   - 帽子のツバや遮蔽物による明度差で影部分がオレンジ・茶色になっていないか
   - 顔の部位ごとに色が不自然に変わっていないか
2. 肌のオレンジみ・黄色みのコントロール（強すぎないか）
3. 色かぶり（芝生・服・背景からの反射）がないか
4. 影の部分の肌色が自然か

### 表情・自然さ
- 自然な笑顔か、硬い・無表情でないか
- 目つぶり・半目がないか
- 主役の表情が見えているか（後ろ向き・顔が隠れていないか）
- 男性側の表情も確認する

### 構図・バランス
- 首切り（地平線・水平線が首の位置）がないか
- 串刺し（木の幹・電柱が頭を貫く）がないか
- 三分割・日の丸構図が正確か
- 余白バランスが適切か
- 進行方向と体の向きが一致しているか

### 背景・整理
- ゴミ箱・椅子・街灯などの不要な要素がないか
- 原色系（赤・青・黄）の物が写り込んでいないか
- 写り込む人物がいないか

### 技術的品質
- ピントが合っているか
- 露出が適切か
- ブレがないか

## 出力JSON

{{
  "photo_ratings": {{
    "{batch_start}": "◎" または "△" または "✕",
    "{batch_start + 1}": "◎" または "△" または "✕"
  }},
  "photo_notes": [
    {{
      "index": {batch_start},
      "issues": ["問題点1（具体的に）", "問題点2"],
      "advice": "改善アドバイス（具体的に）"
    }}
  ]
}}

評価基準：◎ = 合格（納品可能）、△ = 要改善（軽微な問題）、✕ = 不合格（大きな問題）
photo_notesは △ または ✕ の写真のみ含めてください。
"""

def build_summary_prompt(all_ratings, all_notes, total):
    pass_count = sum(1 for v in all_ratings.values() if v == '◎')
    warn_count = sum(1 for v in all_ratings.values() if v == '△')
    fail_count = sum(1 for v in all_ratings.values() if v == '✕')

    return f"""全{total}枚の写真評価結果をまとめてください。

評価結果サマリー：
- 合格（◎）: {pass_count}枚
- 要改善（△）: {warn_count}枚
- 不合格（✕）: {fail_count}枚

個別評価の問題点：
{json.dumps(all_notes, ensure_ascii=False, indent=2)}

以下のJSONのみを出力してください：
{{
  "overall": "合格見込み" または "要改善" または "不合格",
  "summary": "全体的なコメント（2〜3文）",
  "strengths": ["強み1", "強み2", "強み3"],
  "improvements": ["優先改善点1", "優先改善点2", "優先改善点3"],
  "categories": [
    {{"name": "肌色・レタッチ（色の統一感）", "rating": "◎|△|✕", "comment": "コメント"}},
    {{"name": "表情・自然さ", "rating": "◎|△|✕", "comment": "コメント"}},
    {{"name": "構図・バランス", "rating": "◎|△|✕", "comment": "コメント"}},
    {{"name": "背景・整理", "rating": "◎|△|✕", "comment": "コメント"}},
    {{"name": "技術的品質", "rating": "◎|△|✕", "comment": "コメント"}}
  ]
}}
"""

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/evaluate', methods=['POST'])
def evaluate():
    data = request.json
    api_key = data.get('api_key', '').strip()
    images = data.get('images', [])

    if not api_key:
        return jsonify({'error': 'APIキーが必要です'}), 400
    if not images:
        return jsonify({'error': '写真が必要です'}), 400

    def generate():
        try:
            client = anthropic.Anthropic(api_key=api_key)
            total = len(images)
            batches = math.ceil(total / BATCH_SIZE)
            all_ratings = {}
            all_notes = []

            for batch_idx in range(batches):
                start = batch_idx * BATCH_SIZE
                end = min(start + BATCH_SIZE, total)
                batch = images[start:end]

                yield f"data: {json.dumps({'type': 'progress', 'batch': batch_idx + 1, 'total': batches + 1, 'start': start + 1, 'end': end})}\n\n"

                content = []
                for i, img in enumerate(batch):
                    photo_num = start + i + 1
                    img_data = img['data']
                    if ',' in img_data:
                        img_data = img_data.split(',')[1]
                    content.append({'type': 'text', 'text': f'写真 {photo_num}:'})
                    content.append({
                        'type': 'image',
                        'source': {'type': 'base64', 'media_type': img['media_type'], 'data': img_data}
                    })

                content.append({'type': 'text', 'text': build_batch_prompt(start + 1, end, total)})

                message = client.messages.create(
                    model='claude-opus-4-7',
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    messages=[{'role': 'user', 'content': content}]
                )

                response_text = message.content[0].text
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    batch_result = json.loads(response_text[json_start:json_end])
                    all_ratings.update(batch_result.get('photo_ratings', {}))
                    all_notes.extend(batch_result.get('photo_notes', []))

            yield f"data: {json.dumps({'type': 'progress', 'batch': batches + 1, 'total': batches + 1, 'start': total, 'end': total})}\n\n"

            summary_message = client.messages.create(
                model='claude-opus-4-7',
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{'role': 'user', 'content': build_summary_prompt(all_ratings, all_notes, total)}]
            )

            summary_text = summary_message.content[0].text
            json_start = summary_text.find('{')
            json_end = summary_text.rfind('}') + 1
            summary_data = json.loads(summary_text[json_start:json_end])

            result = {
                'type': 'complete',
                'photo_ratings': all_ratings,
                'photo_notes': all_notes,
                **summary_data
            }
            yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"

        except anthropic.AuthenticationError:
            yield f"data: {json.dumps({'type': 'error', 'error': 'APIキーが無効です。正しいキーを入力してください。'})}\n\n"
        except anthropic.RateLimitError:
            yield f"data: {json.dumps({'type': 'error', 'error': 'APIのレート制限に達しました。少し待ってから再試行してください。'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )

if __name__ == '__main__':
    app.run(port=5100, debug=False)
