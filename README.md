> # 리눅스 패키징 구성중입니다! 
# Hwpkit Linux

Linux에서 실행하는 문서 변환·PDF 비교 패키징 프로젝트입니다.
기본 배포물은 CLI이며 `.tar.gz`와 Ubuntu/Debian용 `.deb`를 만듭니다.
현재 작업 중인 `../hwpkit/src`를 빌드하고 연구 프로젝트의 DOC 어댑터/PDF 비교기를 함께 묶습니다.
배포 후 형제 저장소, npm 설치, 데이터셋, LoRA 모델이 필요하지 않습니다.

## 빌드

필요 도구: Python 3.10 이상, Node.js 18 이상, npm. `.deb` 빌드에는 `dpkg-deb`가 필요합니다.
형제 `hwpkit` 및 `hwpkit_research/runner`의 Node 의존성이 준비되어 있어야 합니다.

```bash
cd ../hwpkit && npm ci
cd ../hwpkit_research/runner && npm ci
cd ../../hwpkit-linux
make build
# tar.gz만 생성: python3 scripts/build.py --format tar
```

결과는 `dist/`의 `.tar.gz`, `.deb`, 각 파일의 SHA-256입니다.
빌드는 형제 저장소를 수정하지 않고 임시 폴더에서 수행합니다. 기존 배포 파일은 덮어쓰지 않습니다.
재빌드 시 VERSION을 올리거나 `--output dist/new-build`처럼 새 출력 폴더를 지정하세요.
변환 엔진과 실제 묶인 Node 의존성은 배포물의 `manifest.json`에서 해시·버전을 확인할 수 있습니다.
라이브러리 원본과 빌드 설정은 `sources/`, 의존성 라이선스는 `licenses/`에 포함됩니다.

## Linux에서 실행

Node.js 18 이상, Python 3.10 이상이 필요합니다. DOC 변환/PDF 출력에는 LibreOffice Writer,
PDF 비교에는 PyMuPDF가 추가로 필요합니다. 글꼴은 출력 외관에 영향을 줍니다.

Ubuntu/Debian의 시스템 도구 예시(Node 버전은 `node --version`으로 확인):

```bash
sudo apt install nodejs python3 python3-venv libreoffice-writer fonts-noto-cjk
```

### 압축 패키지

```bash
tar -xzf hwpkit-linux-0.1.0-linux.tar.gz
cd hwpkit-linux-0.1.0-linux
./setup.sh
./bin/hwpkit-linux doctor
./bin/hwpkit-linux convert "/문서/원본.hwp" "/문서/변환.docx"
./bin/hwpkit-linux render "/문서/변환.docx" "/문서/변환.pdf"
./bin/hwpkit-linux compare --reference "/문서/한컴원본.pdf" \
  --generated "/문서/변환.pdf" --output "/문서/비교결과"
```

`setup.sh`는 PyMuPDF를 사용자 전용 가상환경에 설치합니다(최초 설치 시 인터넷 필요).
기본 위치는 `${XDG_DATA_HOME:-$HOME/.local/share}/hwpkit-linux/venv-0.1.0`입니다.
`HWPKIT_LINUX_VENV`로 다른 경로를 지정할 수 있습니다. 설치 후 변환·비교는 로컬에서 실행됩니다.
이 패키지는 Node/Python/LibreOffice 실행 파일을 포함하는 단일 실행 바이너리가 아닙니다.

### Debian 패키지

```bash
sudo apt install ./hwpkit-linux_0.1.0_all.deb
# 배포판의 python3-pymupdf를 쓰거나, PDF 비교 가상환경 설치:
/usr/lib/hwpkit-linux/setup.sh
hwpkit-linux doctor
```

패키지는 `/usr/lib/hwpkit-linux`와 `/usr/bin/hwpkit-linux`에 설치됩니다.
제거는 `sudo apt remove hwpkit-linux`로 수행합니다. 사용자 문서와 사용자 가상환경은 삭제하지 않습니다.

## 명령과 결과

- `convert 입력 출력`: HWP/HWPX/DOCX/MD/HTML 변환. DOC는 DOCX를 거치는 LibreOffice 어댑터 사용.
  DOC↔MD/HTML은 먼저 DOCX로 변환합니다.
- `render 입력.docx 출력.pdf`: LibreOffice로 PDF 생성(DOC도 지원). 한컴 렌더링은 아닙니다.
- `compare --reference 원본.pdf --generated 변환.pdf --output 새폴더`: `review.pdf`, `offsets.csv`, `metrics.json` 생성.
- `doctor`: Node, Python, PyMuPDF, LibreOffice 및 엔진 확인.

기존 출력 파일/비교 폴더를 덮어쓰지 않습니다. 공백/한글 경로를 지원합니다.
한컴 원본 PDF가 기본 비교 기준입니다. 메타데이터가 한컴 제작으로 표시되지 않으면 비교를 중단합니다.
의도적으로 다른 제작 PDF를 진단할 때만 `--allow-other-producer`를 지정합니다.
PDF 메타데이터는 출처의 단서이며 진위를 인증하지 않습니다.

기본 목표는 `--target 0.94`, 위치 허용 오차는 `--tolerance-mm 1`입니다.
**94%는 목표값이며 현재 달성한 정확도가 아닙니다.** 원본과의 표 높이·줄 간격·폰트·쪽 흐름 차이가 남습니다.
목표 충족은 종료 코드 0, 비교 완료/목표 미달은 1, 실행 오류는 2입니다.
`doctor`는 일부 선택 기능의 의존성이 없을 때도 2를 반환하므로 출력 내용을 확인하세요.

## 검증

`make test`는 실제 배포물을 저장소 밖 공백 경로에 풀어 한글 MD→DOCX→PDF 변환과 PDF 비교,
기존 출력 보호, 비한컴 참조 거부를 검사합니다. PDF 검사는 환경에 PyMuPDF/LibreOffice가 필요합니다.
테스트용 Python은 `HWPKIT_TEST_PYTHON`으로 지정할 수 있습니다.
