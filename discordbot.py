import discord
from discord.ext import tasks, commands
import aiohttp
import asyncio
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from datetime import datetime, timedelta, time
import os
import asyncio
from discord.ext import tasks
import json
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib import gridspec
from datetime import datetime, timedelta
import os
import backtrader as bt  # Import backtrader

try:
    # Load Discord token from JSON file
    with open("discordkey.json", "r") as f:
        config = json.load(f)
        DISCORD_TOKEN = str(
            config["key"]
        ).strip()  # Convert to string and remove any whitespace
        print("Token loaded successfully")
        print(
            f"Token length: {len(DISCORD_TOKEN)}"
        )  # Print token length for verification

        # Basic token format verification
        if not DISCORD_TOKEN.strip():
            raise ValueError("Token is empty")

except Exception as e:
    print(f"Error loading token: {e}")
    exit(1)

# Set up bot with commands
intents = discord.Intents.default()
intents.message_content = True  # Enable reading message content
bot = commands.Bot(command_prefix="!", intents=intents)


def create_stock_analysis_plot(
    ticker,
    df,
    expected_weekly_return,
    last_daily_return,
    volatility,
    calls,
    puts,
    expiry_dates,
):
    plt.figure(figsize=(16, 16))
    plt.suptitle(f"{ticker} Analysis", fontsize=16)
    gs = gridspec.GridSpec(4, 2, height_ratios=[3, 1, 2, 2])

    # Calculate date ranges
    end_date = df.index[-1]
    days_90 = pd.Timedelta(days=90)
    days_30 = pd.Timedelta(days=30)
    start_date_90d = end_date - days_90
    start_date_30d = end_date - days_30

    # Price and Moving Averages (spans both columns)
    ax0 = plt.subplot(gs[0, :])
    df.loc[start_date_90d:, ["Close", "EMA20", "EMA50"]].plot(ax=ax0)
    ax0.set_title("Price and Moving Averages (Last 90 Days)")
    ax0.set_ylabel("Price")
    ax0.grid(True)

    # Volume (left column)
    ax1 = plt.subplot(gs[1, 0])
    df.loc[start_date_90d:, "Volume"].plot(ax=ax1, color="blue")
    ax1.set_title("Volume")
    ax1.grid(True)

    # RSI (right column)
    ax2 = plt.subplot(gs[1, 1])
    df.loc[start_date_90d:, "RSI"].plot(ax=ax2, color="purple")
    ax2.axhline(70, color="red", linestyle="--")
    ax2.axhline(30, color="green", linestyle="--")
    ax2.set_title("Relative Strength Index (RSI)")
    ax2.grid(True)

    # Daily Returns (left column)
    ax3 = plt.subplot(gs[2, 0])
    df.loc[start_date_30d:, "Daily Return"].plot(ax=ax3, color="orange")
    ax3.set_title("Daily Returns (%)")
    ax3.grid(True)

    # Risk Analysis (right column)
    ax4 = plt.subplot(gs[2, 1])
    analysis_text = (
        f"Expected Weekly Return: {expected_weekly_return:.2f}%\n"
        f"Last Daily Return: {last_daily_return:.2f}%\n"
        f"Annualized Volatility: {volatility:.2f}%\n"
        f"Max Daily Drop: {df['Daily Return'].min():.2f}%\n"
        f"Best Daily Gain: {df['Daily Return'].max():.2f}%\n"
        f"Current Price: ${df['Close'].iloc[-1]:.2f}"
    )
    ax4.text(
        0.5,
        0.5,
        analysis_text,
        fontsize=12,
        bbox=dict(
            facecolor="white", alpha=0.9, edgecolor="gray", boxstyle="round,pad=1"
        ),
        fontfamily="monospace",
        ha="center",
        va="center",
        transform=ax4.transAxes,
    )
    ax4.axis("off")

    # Options Data (bottom row)
    ax5 = plt.subplot(gs[3, 0])  # Left side for calls
    ax6 = plt.subplot(gs[3, 1])  # Right side for puts
    ax5.axis("off")
    ax6.axis("off")

    if calls is not None and puts is not None:
        calls_text = "CALLS:\n"
        for expiry in expiry_dates:
            if expiry in calls and not calls[expiry].empty:
                calls_text += f"\n{expiry}:\n{calls[expiry].to_string()}\n"
        ax5.text(0, 1.0, calls_text, fontfamily="monospace", va="top")

        puts_text = "PUTS:\n"
        for expiry in expiry_dates:
            if expiry in puts and not puts[expiry].empty:
                puts_text += f"\n{expiry}:\n{puts[expiry].to_string()}\n"
        ax6.text(0, 1.0, puts_text, fontfamily="monospace", va="top")
    else:
        ax5.text(0.5, 0.5, "No options data available", ha="center", va="center")
        ax6.text(0.5, 0.5, "No options data available", ha="center", va="center")

    ax5.set_title("Call Options", pad=20)
    ax6.set_title("Put Options", pad=20)

    os.makedirs("analysis_plots", exist_ok=True)
    plot_filename = f"analysis_plots/{ticker}_analysis.png"

    if os.path.exists(plot_filename):
        os.remove(plot_filename)

    plt.tight_layout()
    plt.savefig(plot_filename, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nAnalysis plot saved to: {plot_filename}")
    return plot_filename


async def stock_analysis(ticker, channel):
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="10mo")

        df["EMA20"] = df["Close"].ewm(span=20, adjust=True).mean()
        df["EMA50"] = df["Close"].ewm(span=50, adjust=True).mean()
        df["Daily Return"] = df["Close"].pct_change() * 100

        delta = df["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df["RSI"] = 100 - (100 / (1 + rs))

        volatility = df["Daily Return"].std() * (252**0.5)

        # Get options data with debug prints
        options = stock.options
        print(f"Available option dates: {options}")  # Debug print

        if options:
            current_price = df["Close"].iloc[-1]
            current_date = datetime.now()

            # Get nearest strike prices (±5 from current price)
            price_range = (round(current_price - 5, 1), round(current_price + 5, 1))
            print(f"Price range: {price_range}")  # Debug print

            # Get options for both 1 week and 2 week expiry
            expiry_dates = []
            for days in [7, 14]:
                potential_date = (current_date + timedelta(days=days)).strftime(
                    "%Y-%m-%d"
                )
                # Find the closest available expiry date
                closest_date = min(
                    options,
                    key=lambda x: abs(
                        datetime.strptime(x, "%Y-%m-%d")
                        - datetime.strptime(potential_date, "%Y-%m-%d")
                    ),
                )
                expiry_dates.append(closest_date)

            print(f"Selected expiry dates: {expiry_dates}")  # Debug print

            calls = {}
            puts = {}

            for expiry in expiry_dates:
                try:
                    opt = stock.option_chain(expiry)
                    print(f"Got options chain for {expiry}")  # Debug print

                    # Filter calls within price range
                    calls[expiry] = opt.calls[
                        (opt.calls["strike"] >= price_range[0])
                        & (opt.calls["strike"] <= price_range[1])
                    ][
                        [
                            "strike",
                            "lastPrice",
                            "openInterest",
                            "bid",
                            "volume",
                            "impliedVolatility",
                            "change",
                        ]
                    ]

                    # Filter puts within price range
                    puts[expiry] = opt.puts[
                        (opt.puts["strike"] >= price_range[0])
                        & (opt.puts["strike"] <= price_range[1])
                    ][
                        [
                            "strike",
                            "lastPrice",
                            "openInterest",
                            "bid",
                            "volume",
                            "impliedVolatility",
                            "change",
                        ]
                    ]

                    print(
                        f"Calls for {expiry}: {len(calls[expiry])} rows"
                    )  # Debug print
                    print(f"Puts for {expiry}: {len(puts[expiry])} rows")  # Debug print

                except Exception as e:
                    print(f"Error getting options for {expiry}: {e}")
                    continue
        else:
            calls = puts = None
            expiry_dates = []
            print("No options available for this stock")  # Debug print

        avg_daily_return = df["Daily Return"].mean()
        expected_weekly_return = avg_daily_return * 5
        last_daily_return = df["Daily Return"].iloc[-1]

        # Create plot and send to Discord
        plot_filename = create_stock_analysis_plot(
            ticker,
            df,
            expected_weekly_return,
            last_daily_return,
            volatility,
            calls,
            puts,
            expiry_dates,
        )

        if plot_filename:
            with open(plot_filename, "rb") as f:
                # Create main embed with analysis
                embed = discord.Embed(
                    title=f"{ticker} Stock Analysis",
                    description="Technical Analysis Report",
                    color=discord.Color.blue(),
                    timestamp=datetime.now(),
                )

                # Add risk analysis to embed
                embed.add_field(
                    name="Risk Analysis",
                    value=f"```\n"
                    f"Expected Weekly Return: {expected_weekly_return:.2f}%\n"
                    f"Last Daily Return: {last_daily_return:.2f}%\n"
                    f"Annualized Volatility: {volatility:.2f}%\n"
                    f"Max Daily Drop: {df['Daily Return'].min():.2f}%\n"
                    f"Best Daily Gain: {df['Daily Return'].max():.2f}%\n"
                    f"Current Price: ${df['Close'].iloc[-1]:.2f}\n"
                    f"```",
                    inline=False,
                )

                file = discord.File(f, filename=f"{ticker}_analysis.png")
                embed.set_image(url=f"attachment://{ticker}_analysis.png")
                await channel.send(file=file, embed=embed)

        else:
            await channel.send(f"Error generating plot for {ticker}")

    except Exception as e:
        print(f"Error analyzing {ticker}: {e}")
        await channel.send(f"Error analyzing {ticker}: {e}")
    finally:
        if "plot_filename" in locals() and os.path.exists(plot_filename):
            os.remove(plot_filename)


@tasks.loop(time=[time(hour=9, minute=30), time(hour=16, minute=0)])
async def scheduled_analysis():
    channel_id = "1222005013392658572"  # Replace with your channel ID
    channel = bot.get_channel(channel_id)

    if channel:
        tickers = ["AAPL", "MSFT", "GOOGL"]
        for ticker in tickers:
            await stock_analysis(ticker, channel)
            await asyncio.sleep(5)
    else:
        print("Channel not found")


@bot.event
async def on_ready():
    print(f"{bot.user} has connected to Discord!")
    scheduled_analysis.start()


@bot.command()
async def analyze(ctx, ticker: str):
    await stock_analysis(ticker, ctx.channel)


@bot.event
async def on_ready():
    print("Bot is ready!")


bot.run(DISCORD_TOKEN)  # Replace with your actual token
