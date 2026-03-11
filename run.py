import argparse
import os

from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    from src.bot import main

    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    debug = args.debug if args.debug else bool(os.getenv("DEBUG"))
    main(debug=debug)
