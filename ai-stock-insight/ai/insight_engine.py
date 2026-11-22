from config.settings import MODEL_NAME
from openai import OpenAI

def get_ai_insight(client, ticker, df, latest_score, signal):
    recent = df.tail(10)[['Close', 'RSI', 'Score']].to_dict(orient='records')

    prompt = f"""
You are a financial analyst.

Ticker: {ticker}
Latest signal: {signal}
Latest score: {latest_score}

Recent data:
{recent}

Explain:
- current trend
- risk level
- short insight in simple terms
"""

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200
    )

    return response.choices[0].message.content.strip()