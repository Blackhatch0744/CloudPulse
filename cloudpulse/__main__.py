import os

from cloudpulse import create_app


def main():
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))


if __name__ == "__main__":
    main()
