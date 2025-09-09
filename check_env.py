import os

from dotenv import load_dotenv

load_dotenv(override=True)
print("Token snippet:", str(os.getenv("DISCORD_TOKEN"))[:10])
print("League ID:", os.getenv("SLEEPER_LEAGUE_ID"))
