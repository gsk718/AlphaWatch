import plotly.graph_objects as go
from plotly.subplots import make_subplots

def plot_stock(df, ticker, insight):
    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[0.7, 0.3],
        vertical_spacing=0.1
    )

    # Price + MAs
    fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], name="Close"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['Date'], y=df['MA_SHORT'], name="MA Short"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['Date'], y=df['MA_LONG'], name="MA Long"), row=1, col=1)

    # RSI subplot
    fig.add_trace(go.Scatter(x=df['Date'], y=df['RSI'], name="RSI"), row=2, col=1)

    fig.update_layout(
        title=f"{ticker} Analysis",
        height=700
    )

    fig.show()

    print("\nAI INSIGHT:\n", insight)