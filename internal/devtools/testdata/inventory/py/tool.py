import argparse

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers()
    sub.add_parser("collect")
    sub.add_parser("render")

if __name__ == "__main__":
    main()
