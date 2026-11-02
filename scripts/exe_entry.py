"""exe 진입점. `morning_brief.exe init` 은 양식과 설정 파일을 만들고, 인자가 없으면 아침 점검을 한 번 돌린다."""
import sys

from brief import init, main

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        sys.argv.pop(1)
        init.main()
    else:
        main.main()
