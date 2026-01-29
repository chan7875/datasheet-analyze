# Datasheet Analyzer (AI Powered)

**Datasheet Analyzer**는 PDF 형태의 부품 데이터시트를 OpenAI(GPT-4 Vision)를 활용하여 자동으로 분석하고, 회로 설계 시 필요한 핵심 정보와 체크포인트를 추출해주는 PyQt6 기반 데스크톱 애플리케이션입니다.

## 주요 기능 (Features)

*   **자동 감지 (File Monitoring):** 지정된 폴더에 PDF나 이미지 파일이 추가되면 자동으로 감지하여 분석을 시작합니다.
*   **AI 상세 분석:**
    *   **부품 태그 추출:** 벤더 코드(Model Name), 입출력 전압, 전류 등 스펙 정보를 메타데이터로 추출합니다.
    *   **기능 요약:** 데이터시트의 주요 기능, 핀 배치, 외부 부품 권장값, 레퍼런스 회로 정보를 요약합니다.
    *   **체크포인트 생성:** PCB 설계(Graphic/Schema) 단계에서 검증해야 할 항목(Decoupling Capacitor, Pull-up/down 등)을 리스트업합니다.
*   **코드 연동:** 추출된 체크포인트를 검증할 수 있는 Python 스크립트 스니펫을 자동으로 생성합니다.
*   **로컬 DB 저장:** 분석된 결과는 SQLite 데이터베이스에 저장되어 언제든 다시 열람할 수 있습니다.

## 설치 및 실행 (Installation)

### 필요 사항 (Prerequisites)
*   Python 3.8 이상
*   OpenAI API Key (GPT-4 Vision 모델 사용 권장)

### 설치 (Installation)

1.  저장소 클론:
    ```bash
    git clone https://github.com/chan7875/datasheet-analyze.git
    cd datasheet-analyze
    ```

2.  의존성 패키지 설치:
    ```bash
    pip install -r requirements.txt
    ```

### 실행 (Usage)

1.  애플리케이션 실행:
    ```bash
    python main.py
    ```

2.  **초기 설정:**
    *   우측 상단의 `API 설정` 버튼을 눌러 **OpenAI API Key**를 입력합니다.
    *   `폴더 선택`을 통해 데이터시트를 저장할 폴더를 지정합니다.

3.  **분석:**
    *   설정된 폴더에 PDF 데이터시트 파일을 넣으면 자동으로 분석이 시작됩니다.
    *   분석이 완료되면(Status: Finish), 파일 리스트를 클릭하여 결과를 확인합니다.

## 프로젝트 구조

*   `main.py`: 메인 애플리케이션 진입점, UI 및 로직 처리
*   `database.py`: SQLite DB 관리 (분석 결과, 메타데이터, 체크포인트 저장)
*   `requirements.txt`: 필요 라이브러리 목록

## 기술 스택

*   **Language:** Python
*   **GUI:** PyQt6
*   **AI:** OpenAI API (GPT-4)
*   **PDF Processing:** PyMuPDF (fitz)
*   **File Monitoring:** Watchdog
*   **Database:** SQLite3

## 주의 사항
*   이 프로그램은 OpenAI API를 사용하므로, 사용량에 따라 API 비용이 발생할 수 있습니다.
*   분석 결과는 AI가 생성한 것이므로, 실제 설계 적용 시 반드시 원본 데이터시트와 교차 검증하시기 바랍니다.
