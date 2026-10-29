import sys

from support_bot.loop import answer_ticket

if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or sys.stdin.read()
    print(answer_ticket(question))
