"""
Data Analyzer - Python PyQt6 Version
PDF 데이터시트를 AI로 자동 분석하는 애플리케이션
"""

import os
import base64
import tempfile
import subprocess
from enum import Enum
from pathlib import Path
from typing import Optional, List
from threading import Thread

# PyQt6
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QLabel, QLineEdit, QPushButton,
    QTextBrowser, QSplitter, QHeaderView, QFileDialog, QMessageBox,
    QDialog, QTabWidget
)
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QSettings
from PyQt6.QtGui import QPixmap, QImage

# File monitoring
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# PDF processing
import fitz  # PyMuPDF

# OpenAI
import openai

# Database
from database import DatasheetDatabase, calculate_file_hash


# ============================================================================
# Data Model
# ============================================================================

class CreatingResultFileStatus(Enum):
    """분석 결과 파일 생성 상태"""
    READY = "Ready"
    PROCESSING = "Processing"
    FINISH = "Finish"


class DataSheetInfo:
    """데이터시트 파일 정보"""

    def __init__(self, datasheet_filename: str, folder_path: str):
        self.datasheet_filename = datasheet_filename
        self.folder_path = folder_path
        self._status = CreatingResultFileStatus.READY

    @property
    def result_filename(self) -> str:
        """결과 파일명: datasheet.pdf → datasheet_pdf.mounterlib"""
        return self.datasheet_filename.replace(".", "_") + ".mounterlib"

    @property
    def status(self) -> CreatingResultFileStatus:
        """상태"""
        return self._status

    @status.setter
    def status(self, value: CreatingResultFileStatus):
        self._status = value


# ============================================================================
# File System Monitoring
# ============================================================================

class DatasheetFileHandler(FileSystemEventHandler):
    """파일 시스템 변경 감지 핸들러"""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def on_created(self, event):
        if not event.is_directory:
            self.callback('created', event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self.callback('deleted', event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self.callback('renamed', event.src_path, event.dest_path)


# ============================================================================
# PDF/Image Utilities
# ============================================================================

def pdf_to_base64_images(pdf_path: str, max_pages: int = 5, dpi: int = 150) -> List[str]:
    """PDF를 Base64 인코딩된 이미지 리스트로 변환"""
    images = []

    try:
        doc = fitz.open(pdf_path)

        for page_num in range(min(len(doc), max_pages)):
            page = doc[page_num]
            pix = page.get_pixmap(dpi=dpi)
            img_bytes = pix.tobytes("png")
            base64_img = base64.b64encode(img_bytes).decode('utf-8')
            images.append(f"data:image/png;base64,{base64_img}")

        doc.close()

    except Exception as e:
        print(f"PDF 이미지 변환 실패: {e}")
        raise

    return images


def load_pdf_as_pixmap(pdf_path: str, dpi: int = 150) -> Optional[QPixmap]:
    """PDF 첫 페이지를 QPixmap으로 로드"""
    try:
        doc = fitz.open(pdf_path)
        page = doc[0]  # 첫 페이지만

        pix = page.get_pixmap(dpi=dpi)
        img_data = pix.tobytes("png")

        qimage = QImage.fromData(img_data)
        pixmap = QPixmap.fromImage(qimage)

        doc.close()
        return pixmap

    except Exception as e:
        print(f"PDF 로드 실패: {e}")
        return None

# ============================================================================
# Settings Dialog
# ============================================================================

class SettingsDialog(QDialog):
    """설정 다이얼로그"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.setModal(True)
        self.resize(500, 250)

        # QSettings로 설정 저장/로드
        self.settings = QSettings("DatasheetAnalyzer", "Settings")

        # UI 초기화
        layout = QVBoxLayout(self)

        # OpenAI API Key
        api_key_layout = QHBoxLayout()
        api_key_layout.addWidget(QLabel("OpenAI API Key:"))

        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("sk-proj-...")

        # 저장된 API 키 로드
        saved_key = self.settings.value("openai_api_key", "")
        self.api_key_input.setText(saved_key)

        api_key_layout.addWidget(self.api_key_input)

        # 표시/숨김 버튼
        self.toggle_btn = QPushButton("표시")
        self.toggle_btn.setMaximumWidth(60)
        self.toggle_btn.clicked.connect(self.toggle_password)
        api_key_layout.addWidget(self.toggle_btn)

        layout.addLayout(api_key_layout)

        # CubicLDRC 실행 파일 경로
        ldrc_layout = QHBoxLayout()
        ldrc_layout.addWidget(QLabel("CubicLDRC 경로:"))

        self.ldrc_path_input = QLineEdit()
        self.ldrc_path_input.setPlaceholderText("C:\\Program Files (x86)\\Pentacube\\Cubic\\CubicLDRC\\Normal\\CubicLDRC.exe")

        # 저장된 경로 로드
        default_path = r"C:\Program Files (x86)\Pentacube\Cubic\CubicLDRC\Normal\CubicLDRC.exe"
        saved_path = self.settings.value("cubic_ldrc_path", default_path)
        self.ldrc_path_input.setText(saved_path)

        ldrc_layout.addWidget(self.ldrc_path_input)

        # 찾아보기 버튼
        browse_btn = QPushButton("찾아보기")
        browse_btn.setMaximumWidth(80)
        browse_btn.clicked.connect(self.browse_ldrc_path)
        ldrc_layout.addWidget(browse_btn)

        layout.addLayout(ldrc_layout)

        # 버튼
        button_layout = QHBoxLayout()

        save_btn = QPushButton("저장")
        save_btn.clicked.connect(self.save_settings)
        button_layout.addWidget(save_btn)

        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def toggle_password(self):
        """비밀번호 표시/숨김 토글"""
        if self.api_key_input.echoMode() == QLineEdit.EchoMode.Password:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.toggle_btn.setText("숨김")
        else:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.toggle_btn.setText("표시")

    def browse_ldrc_path(self):
        """CubicLDRC 실행 파일 찾아보기"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "CubicLDRC 실행 파일 선택",
            "C:\\Program Files (x86)\\Pentacube\\Cubic\\CubicLDRC\\Normal",
            "실행 파일 (*.exe)"
        )

        if file_path:
            self.ldrc_path_input.setText(file_path)

    def save_settings(self):
        """설정 저장"""
        api_key = self.api_key_input.text().strip()
        ldrc_path = self.ldrc_path_input.text().strip()

        if not api_key:
            QMessageBox.warning(self, "경고", "API 키를 입력해주세요.")
            return

        if not ldrc_path:
            QMessageBox.warning(self, "경고", "CubicLDRC 경로를 입력해주세요.")
            return

        if not os.path.exists(ldrc_path):
            QMessageBox.warning(self, "경고", "CubicLDRC 실행 파일이 존재하지 않습니다.")
            return

        # QSettings에 저장
        self.settings.setValue("openai_api_key", api_key)
        self.settings.setValue("cubic_ldrc_path", ldrc_path)

        QMessageBox.information(self, "성공", "설정이 저장되었습니다.")
        self.accept()

    def get_api_key(self) -> str:
        """저장된 API 키 반환"""
        return self.settings.value("openai_api_key", "")


# ============================================================================
# SMT Library Folder Manager Tab
# ============================================================================

class DataAnalyzerTab(QWidget):
    """Data Analyzer 탭"""

    # 시그널 정의
    update_table_signal = pyqtSignal()
    refresh_result_viewer_signal = pyqtSignal(str)

    # VendorCode 추출 프롬포트
    VENDORCODE_PROMPT = "해당 문서 또는 이미지의 벤더코드를 추출해주세요. 다른 코멘트 없이 벤더코드로만 답변하세요."
    # 분석 프롬프트
    ANALYZE_PROMPT = """해당 문서는 회로 부품의 Datasheet입니다.
            1. Datasheet 또는 회로도 Image 문서를 분석합니다.
            3. 해당 Datasheet에서, 벤더코드를 찾고 해당 벤더코드의 데이터 시트를 분석해주세요.
            4. PCB Artwork를 설계해주세요.
            5. 아래와 같은 포맷으로 한글로 답변해 주세요.
            [예시]
            ## 1. IC 데이터 시트 분석
            ----------------
            ### 1.1 주요 기능

            *   입력 전압 범위: 7.5 V ~ 76 V, 내부 언더볼티지 락아웃(UVLO) 5.2 V (typ)
            *   출력 전압: MAX5033A 고정 3.3 V (±3.5%), 최대 500 mA 출력 가능 
            *   스위칭 주파수: 125 kHz 고정, 과부하 시 펄스 스키핑 모드로 전환하여 경부하 효율 최적화
            *   저전력 특성: 무부하 대기 전류 270 µA, 셧다운 시 10 µA 
            *   보호 기능: 사이클별 전류 제한, 쇼트 회로 히컵 모드, 열 과부하 보호(Tj = +160 °C)

            ### 1.2 핀 배치 및 기능
            |핀 번호| 핀 이름      | 기능 설명   |
            |-------|--------------|-------------|
            |1|BST|부스트 게이트 드라이브 커패시터 연결 (BST↔LX, 0.1 µF/16 V 세라믹 권장)|
            |2|VD|내부 레귤레이터 출력. VD↔GND에 0.1 µF 세라믹 커패시터로 바이패스|
            |3|SGND|내부 아날로그 그라운드. PCB GND와 동일 전위로 연결|
            |4|FB|출력 전압 피드백. MAX5033A는 내부 고정, FB↔VOUT 연결|
            |5|ON/OFF|셧다운 제어 입력. Low(≤0.4 V) 셧다운, High(≥1.69 V) 작동 (히스테리시스 100 mV)|
            |6|GND|파워 그라운드. 높은 전류 루프에 사용|
            |7|VIN|입력 전압. VIN↔GND에 저ESR 입력 커패시터(47 µF + 0.1 µF 세라믹) 권장|
            |8|LX|내부 하이사이드 스위치 소스. 인덕터, 프리휠링 다이오드와 연결|

            ### 1.3 외부 부품 권장값 및 레퍼런스 회로

            *   **입력 커패시터 (CIN):** 47 µF 저ESR 알루미늄 전해 + 0.1 µF 세라믹을 병렬 사용. 입력 리플 억제 및 소스 안정화에 필수
            *   **인덕터 (L1):** VOUT=3.3 V/IOUT=0.5 A 기준 220 µH, 포화 전류는 피크 스위치 리밋(≈1.5 A) 이상 선택
            *   **출력 커패시터 (COUT):** 33 µF, ESR 100 mΩ~250 mΩ (타이밍·안정화 제어용 zero 형성)
            *   **부스트 커패시터 (CBST):** 0.1 µF/16 V 세라믹, BST↔LX에 몰딩 위치 최소화
            *   **VD 디커플링 (CVD):** 0.1 µF 세라믹, VD↔GND
            *   **프리휠링 다이오드 (D1):** 50SQ100(50 V/1 A Schottky) 권장, 낮은 Vf (<0.45 V)
            *   **UVLO 설정용 저항 분압 (R1, R2):** 예시로 R1=41.2 kΩ, R2=13.3 kΩ 설정 시 ON/OFF = 7.5 V에서 동작 시작

            ## 2. PCB Artwork 정보
            *   PCB Artwork 할 때, 회로 구성 중, 특정 부품간의 이격거리나 Trace 길이에 대한 가이드 정보
            *   PCB Artwork 상의 Net 간의 이격거리 정보
            *   기타 Artwork 기반의 이격거리 정보, Routing 주의 사항
            *   라이브러리를 만들기 위한 부품 실물 정보(Pin 규격, 부품 실제 크기 등)
            """
    # 태그 생성 프롬포트
    TAG_PROMPT = """1. 검색용 메타데이터로 사용할 수 있도록 IC 태그 정보를 json 형태로 만들어주세요.
            2. 예시에 없는 Name의 태그를 생성해도 좋습니다.
            3. 데이터 시트를 분석했다면, Name이 Model인 태그는 필수입니다. 분석된 벤더코드가 없다면 Model 태그를 생성하지 마세요.
            [예시]
            ```
            [
                {
                    'Name' : 'Model',
                    'Description' : 'MAX5033A',
                },
                {
                    'Name' : '입력 전압',
                    'Description' : '10.5V DC'
                },
                {
                    'Name' : '출력 전압',
                    'Description' : '3.3V DC'
                },
                {
                    'Name' : '출력 전류',
                    'Description' : '최대 3A'
                },
                {
                    'Name' : '컨버터 타입',
                    'Description' : 'Buck (Step-Down)'
                },
                {
                    'Name' : '메인 칩셋',
                    'Description' : 'MP1497SGJ'
                },
                {
                    'Name' : '스위칭 주파수',
                    'Description' : 'MP1497 데이터시트 기준 (약 500kHz)'
                },
            ]
            ```"""
    
    # 체크포인트 생성 프롬포트
    CHECKPOINT_PROMPT="""해당 데이터시트 확인해서 회로도 그렸을 때 확인해야 하는 사항에 대해 리스트업 해 주고, 
            ic 인 경우에는 핀별로 꼭 연결을 해야 하는 부품이나 풀업, 풀다운, 전원 연결, gnd 연결이 되어야 할 경우에 리스트업 해 줘. 
            해당 리스트를 json으로 반환해줘. 간단하게 string 배열로 반환해줘.
            (VendorCode)에는, 해당 데이터시트에서 찾은 부품의 VendorCode를 넣어줘.

            결과 예시는 `(VendorCode)의 VIN 핀이 입력 전압원과 디커플링 커패시터를 GND(일반적으로 10 µF)에 연결되었는지 확인` 이런식으로 확인해달라는 뉘앙스로 만들어줘."""

    def _get_python_code_prompt(self, checkPointText: str, symbolName: str):
        return "Create Python code for VendorCode" + symbolName + ". Requirement: " + checkPointText + ". Output only python code."
    
    def __init__(self):
        super().__init__()

        # 데이터
        self.datasheets: List[DataSheetInfo] = []
        self.current_checkpoints: List[dict] = []  # 현재 표시 중인 체크포인트 목록

        # QSettings에서 폴더 경로 로드
        self.settings = QSettings("DatasheetAnalyzer", "Settings")
        self.folder_path = self.settings.value("folder_path", "C:\\datasheets")
        self.openai_api_key = self.settings.value("openai_api_key", "")
        self.cubic_ldrc_path = self.settings.value("cubic_ldrc_path", r"C:\Program Files (x86)\Pentacube\Cubic\CubicLDRC\Normal\CubicLDRC.exe")

        # 데이터베이스 초기화
        self.db = DatasheetDatabase()

        # 파일 모니터링
        self.observer: Optional[Observer] = None

        # 타이머
        self.analysis_timer = QTimer()

        # UI 초기화
        self.init_ui()

        # 폴더 설정 확인
        if os.path.exists(self.folder_path):
            self.load_datasheets()
            self.start_file_monitoring()
        else:
            self.show_folder_setup_message()

        # 시그널 연결
        self.update_table_signal.connect(self.update_table)
        self.refresh_result_viewer_signal.connect(self.refresh_result_viewer_if_selected)

        # 타이머 시작 (60000ms = 1분)
        self.analysis_timer.timeout.connect(self.on_analysis_timer)
        self.analysis_timer.start(60000)

    def init_ui(self):
        """UI 초기화"""
        # 메인 레이아웃
        main_layout = QVBoxLayout(self)

        # 상단: 폴더 경로 설정
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("폴더 경로:"))

        self.folder_path_edit = QLineEdit(self.folder_path)
        top_layout.addWidget(self.folder_path_edit)

        set_folder_btn = QPushButton("폴더 선택")
        set_folder_btn.clicked.connect(self.on_set_folder)
        top_layout.addWidget(set_folder_btn)

        # 재분석 버튼
        reanalyze_btn = QPushButton("재분석")
        reanalyze_btn.clicked.connect(self.on_reanalyze)
        top_layout.addWidget(reanalyze_btn)

        # API 설정 버튼
        settings_btn = QPushButton("API 설정")
        settings_btn.clicked.connect(self.on_open_settings)
        top_layout.addWidget(settings_btn)

        # DB 통계 버튼
        db_stats_btn = QPushButton("DB 통계")
        db_stats_btn.clicked.connect(self.on_load_from_db)
        top_layout.addWidget(db_stats_btn)

        main_layout.addLayout(top_layout)

        # 메인 스플리터
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 왼쪽: 데이터시트 목록 (QTableWidget)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["☐", "파일명", "상태", "결과파일"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().resizeSection(0, 30)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        self.table.itemDoubleClicked.connect(self.on_table_double_clicked)
        self.table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)

        splitter.addWidget(self.table)

        # 오른쪽 컨테이너 (메타데이터 + PDF 뷰어 + 분석결과)
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 분석 결과와 체크포인트를 담을 스플리터
        content_splitter = QSplitter(Qt.Orientation.Horizontal)

        # 분석 결과 영역 (탭으로 구성)
        result_widget = QWidget()
        result_layout = QVBoxLayout(result_widget)
        result_layout.setContentsMargins(0, 0, 0, 0)

        # 탭 위젯 생성
        self.result_tabs = QTabWidget()

        # 탭 1: 부품 정보
        metadata_tab = QWidget()
        metadata_layout = QVBoxLayout(metadata_tab)
        metadata_layout.setContentsMargins(5, 5, 5, 5)

        self.metadata_table = QTableWidget()
        self.metadata_table.setColumnCount(2)
        self.metadata_table.setHorizontalHeaderLabels(["Key", "Value"])
        self.metadata_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.metadata_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.metadata_table.verticalHeader().setVisible(False)
        self.metadata_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        metadata_layout.addWidget(self.metadata_table)

        self.result_tabs.addTab(metadata_tab, "부품 정보")

        # 탭 2: 분석 결과
        analysis_tab = QWidget()
        analysis_layout = QVBoxLayout(analysis_tab)
        analysis_layout.setContentsMargins(5, 5, 5, 5)

        self.result_text = QTextBrowser()
        self.result_text.setOpenExternalLinks(True)
        analysis_layout.addWidget(self.result_text)

        self.result_tabs.addTab(analysis_tab, "분석 결과")

        result_layout.addWidget(self.result_tabs)

        content_splitter.addWidget(result_widget)

        # 체크포인트 영역 (체크포인트 목록 + Python 코드를 수직 스플리터로 구성)
        checkpoint_widget = QWidget()
        checkpoint_main_layout = QVBoxLayout(checkpoint_widget)
        checkpoint_main_layout.setContentsMargins(0, 0, 0, 0)

        # 체크포인트와 Python 코드를 담을 수직 스플리터
        checkpoint_splitter = QSplitter(Qt.Orientation.Vertical)

        # 체크포인트 목록 위젯
        checkpoint_list_widget = QWidget()
        checkpoint_list_layout = QVBoxLayout(checkpoint_list_widget)
        checkpoint_list_layout.setContentsMargins(0, 0, 0, 0)
        checkpoint_list_layout.addWidget(QLabel("체크포인트:"))

        self.checkpoint_list = QTableWidget()
        self.checkpoint_list.setColumnCount(1)
        self.checkpoint_list.setHorizontalHeaderLabels(["확인 사항"])
        self.checkpoint_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.checkpoint_list.verticalHeader().setVisible(False)
        self.checkpoint_list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.checkpoint_list.itemSelectionChanged.connect(self.on_checkpoint_selection_changed)
        checkpoint_list_layout.addWidget(self.checkpoint_list)

        checkpoint_splitter.addWidget(checkpoint_list_widget)

        # Python 코드 위젯
        python_code_widget = QWidget()
        python_code_layout = QVBoxLayout(python_code_widget)
        python_code_layout.setContentsMargins(0, 0, 0, 0)
        python_code_layout.addWidget(QLabel("Python 코드:"))

        self.python_code_text = QTextBrowser()
        self.python_code_text.setStyleSheet("font-family: 'Consolas', 'Courier New', monospace;")
        python_code_layout.addWidget(self.python_code_text)

        checkpoint_splitter.addWidget(python_code_widget)

        # 스플리터 비율 설정 (1:1)
        checkpoint_splitter.setSizes([500, 500])

        checkpoint_main_layout.addWidget(checkpoint_splitter)

        content_splitter.addWidget(checkpoint_widget)

        # 스플리터 비율 설정 (분석 결과 60%, 체크포인트 40%)
        content_splitter.setSizes([600, 400])

        right_layout.addWidget(content_splitter)

        splitter.addWidget(right_container)

        # 메인 스플리터 비율 설정
        splitter.setSizes([400, 1000])

        main_layout.addWidget(splitter)

    def show_folder_setup_message(self):
        """폴더 설정 안내 메시지"""
        self.result_text.setPlainText("폴더를 선택하면 분석이 시작됩니다.")

    def on_set_folder(self):
        """폴더 설정 버튼 클릭"""
        folder = QFileDialog.getExistingDirectory(self, "데이터시트 폴더 선택", self.folder_path)

        if folder:
            self.folder_path = folder
            self.folder_path_edit.setText(folder)

            # QSettings에 폴더 경로 저장
            self.settings.setValue("folder_path", folder)

            # 파일 모니터링 중지
            self.stop_file_monitoring()

            # 데이터시트 로드
            self.load_datasheets()

            # 파일 모니터링 시작
            self.start_file_monitoring()

    def on_reanalyze(self):
        """체크된 데이터시트 재분석"""
        # 체크된 항목 찾기
        checked_rows = []
        for i in range(self.table.rowCount()):
            checkbox_item = self.table.item(i, 0)
            if checkbox_item and checkbox_item.checkState() == Qt.CheckState.Checked:
                checked_rows.append(i)

        if not checked_rows:
            QMessageBox.warning(self, "경고", "재분석할 데이터시트를 체크해주세요.")
            return

        # 체크된 모든 항목 재분석
        for row in checked_rows:
            if row < len(self.datasheets):
                datasheet = self.datasheets[row]

                # DB에서 기존 결과 삭제
                db_result = self.db.get_analysis_by_filename(datasheet.datasheet_filename)
                if db_result:
                    self.db.delete_analysis(db_result['id'])

                # 상태를 Ready로 변경
                datasheet.status = CreatingResultFileStatus.READY

        self.update_table()
        QMessageBox.information(self, "재분석", f"{len(checked_rows)}개의 파일이 재분석 대기 중입니다.")

    def on_open_settings(self):
        """API 설정 다이얼로그 열기"""
        dialog = SettingsDialog(self)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            # API 키 및 CubicLDRC 경로 다시 로드
            self.openai_api_key = self.settings.value("openai_api_key", "")
            self.cubic_ldrc_path = self.settings.value("cubic_ldrc_path", r"C:\Program Files (x86)\Pentacube\Cubic\CubicLDRC\Normal\CubicLDRC.exe")
            print(f"설정이 업데이트되었습니다.")

    def on_load_from_db(self):
        """DB 통계 보기"""
        # 통계 정보 가져오기
        stats = self.db.get_statistics()

        # 메시지 박스로 통계 표시
        stats_text = f"전체 분석 개수: {stats['total_analysis']}\n"
        stats_text += f"최근 분석: {stats['latest_analysis']}\n\n"
        stats_text += "벤더별 통계:\n"

        for vendor_stat in stats['vendor_stats'][:5]:
            vendor = vendor_stat['vendor_code'] or '미지정'
            count = vendor_stat['count']
            stats_text += f"  - {vendor}: {count}개\n"

        QMessageBox.information(self, "DB 통계", stats_text)

    def load_datasheets(self):
        """데이터시트 폴더에서 파일 목록 로드"""
        self.datasheets.clear()
        self.table.setRowCount(0)

        # 파일 목록 로드
        if not os.path.exists(self.folder_path):
            return

        for filename in os.listdir(self.folder_path):
            file_path = os.path.join(self.folder_path, filename)

            # 파일만 (디렉토리 제외)
            if os.path.isfile(file_path):
                # PDF 또는 이미지 파일만
                ext = os.path.splitext(filename)[1].lower()
                if ext in ['.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff']:
                    datasheet = DataSheetInfo(filename, self.folder_path)

                    # DB에서 상태 확인
                    db_result = self.db.get_analysis_by_filename(filename)
                    if db_result:
                        datasheet.status = CreatingResultFileStatus.FINISH

                    self.datasheets.append(datasheet)

        # 테이블 업데이트
        self.update_table()

    def update_table(self):
        """테이블 업데이트"""
        self.table.setRowCount(len(self.datasheets))

        for i, datasheet in enumerate(self.datasheets):
            # 체크박스
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            checkbox_item.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(i, 0, checkbox_item)

            # 파일명
            self.table.setItem(i, 1, QTableWidgetItem(datasheet.datasheet_filename))

            # 상태
            status_text = datasheet.status.value
            self.table.setItem(i, 2, QTableWidgetItem(status_text))

            # DB 결과 여부 확인
            db_result = self.db.get_analysis_by_filename(datasheet.datasheet_filename)
            has_result = "있음" if db_result else "없음"
            self.table.setItem(i, 3, QTableWidgetItem(has_result))

    def on_selection_changed(self):
        """테이블 선택 변경"""
        try:
            selected_rows = self.table.selectedIndexes()

            if not selected_rows:
                self.result_text.clear()
                self.checkpoint_list.setRowCount(0)
                self.python_code_text.clear()
                return

            row = selected_rows[0].row()
            datasheet = self.datasheets[row]

            # 파일 경로
            file_path = os.path.join(self.folder_path, datasheet.datasheet_filename)

            # 파일 존재 확인
            if not os.path.exists(file_path):
                self.result_text.setPlainText("파일을 찾을 수 없습니다")
                self.checkpoint_list.setRowCount(0)
                self.python_code_text.clear()
                return

            # DB에서 결과 로드
            db_result = self.db.get_analysis_by_filename(datasheet.datasheet_filename)
            if db_result:
                self.result_text.setMarkdown(db_result['analysis_result'])

                # 메타데이터 로드 및 표시
                metadata = self.db.get_metadata(db_result['id'])
                self.update_metadata_table(metadata)

                # 체크포인트 로드 및 표시
                checkpoints = self.db.get_checkpoints_by_datasheet(db_result['id'])
                self.update_checkpoint_list(checkpoints)
            else:
                self.result_text.setPlainText("분석 결과가 없습니다.")
                self.metadata_table.setRowCount(0)
                self.checkpoint_list.setRowCount(0)
                self.python_code_text.clear()
        except Exception as e:
            print(f"선택 변경 오류: {e}")
            self.result_text.setPlainText(f"오류: {str(e)}")
            self.metadata_table.setRowCount(0)
            self.checkpoint_list.setRowCount(0)
            self.python_code_text.clear()

    def update_metadata_table(self, metadata: dict):
        """메타데이터 테이블 업데이트"""
        if not metadata:
            self.metadata_table.setRowCount(0)
            return

        # 행 수 설정 (각 메타데이터 항목마다 한 행)
        self.metadata_table.setRowCount(len(metadata))

        # Key와 Value를 각 행에 설정
        for row, (key, value) in enumerate(metadata.items()):
            # Key 열
            key_item = QTableWidgetItem(key)
            self.metadata_table.setItem(row, 0, key_item)

            # Value 열
            value_item = QTableWidgetItem(str(value))
            self.metadata_table.setItem(row, 1, value_item)

        # 컬럼 크기 자동 조정
        self.metadata_table.resizeColumnsToContents()

    def update_checkpoint_list(self, checkpoints: List[dict]):
        """체크포인트 목록 업데이트"""
        self.current_checkpoints = checkpoints
        self.checkpoint_list.setRowCount(len(checkpoints))

        for row, checkpoint in enumerate(checkpoints):
            text = checkpoint.get('text', '')
            item = QTableWidgetItem(text)
            self.checkpoint_list.setItem(row, 0, item)

        # Python 코드 영역 초기화
        self.python_code_text.clear()

    def on_checkpoint_selection_changed(self):
        """체크포인트 선택 변경 이벤트"""
        selected_rows = self.checkpoint_list.selectedIndexes()

        if not selected_rows:
            self.python_code_text.clear()
            return

        row = selected_rows[0].row()

        if row < 0 or row >= len(self.current_checkpoints):
            self.python_code_text.clear()
            return

        checkpoint = self.current_checkpoints[row]
        python_code = checkpoint.get('python_code', '')

        if python_code:
            self.python_code_text.setPlainText(python_code)
        else:
            self.python_code_text.setPlainText("# Python 코드가 없습니다.")

    def on_table_double_clicked(self, item):
        """테이블 더블클릭 이벤트"""
        row = item.row()
        if row < 0 or row >= len(self.datasheets):
            return

        datasheet = self.datasheets[row]
        file_path = os.path.join(self.folder_path, datasheet.datasheet_filename)

        # 파일 존재 확인
        if os.path.exists(file_path):
            # 운영체제 기본 프로그램으로 열기
            os.startfile(file_path)

    def on_header_clicked(self, logical_index):
        """헤더 클릭 이벤트 (체크박스 전체 선택/해제)"""
        if logical_index == 0:  # 체크박스 열
            # 현재 체크 상태 확인
            checked_count = 0
            total_count = self.table.rowCount()

            for i in range(total_count):
                checkbox_item = self.table.item(i, 0)
                if checkbox_item and checkbox_item.checkState() == Qt.CheckState.Checked:
                    checked_count += 1

            # 전체 선택/해제 토글
            new_state = Qt.CheckState.Unchecked if checked_count > 0 else Qt.CheckState.Checked

            for i in range(total_count):
                checkbox_item = self.table.item(i, 0)
                if checkbox_item:
                    checkbox_item.setCheckState(new_state)

            # 헤더 텍스트 업데이트
            header_text = "☑" if new_state == Qt.CheckState.Checked else "☐"
            self.table.horizontalHeaderItem(0).setText(header_text)

    # ========================================================================
    # File Monitoring
    # ========================================================================

    def start_file_monitoring(self):
        """파일 모니터링 시작"""
        if self.observer:
            return

        handler = DatasheetFileHandler(self.on_file_changed)
        self.observer = Observer()
        self.observer.schedule(handler, self.folder_path, recursive=True)
        self.observer.start()

    def stop_file_monitoring(self):
        """파일 모니터링 중지"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None

    def on_file_changed(self, event_type: str, src_path: str, dest_path: str = None):
        """파일 변경 이벤트 처리"""
        # results 폴더인지 확인
        is_results_folder = "results" in src_path

        if event_type == 'created':
            if not is_results_folder:
                # 루트 폴더에 새 데이터시트 생성
                filename = os.path.basename(src_path)
                ext = os.path.splitext(filename)[1].lower()

                if ext in ['.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff']:
                    datasheet = DataSheetInfo(filename, self.folder_path)
                    self.datasheets.append(datasheet)
                    self.update_table()
            else:
                # results 폴더에 결과 파일 생성
                self.update_table()
                self.refresh_result_viewer_signal.emit(src_path)

        elif event_type == 'deleted':
            if not is_results_folder:
                # 루트 폴더에서 데이터시트 삭제
                filename = os.path.basename(src_path)
                self.datasheets = [d for d in self.datasheets if d.datasheet_filename != filename]
                self.update_table()
            else:
                # results 폴더에서 결과 파일 삭제
                self.update_table()
                self.refresh_result_viewer_signal.emit(src_path)

        elif event_type == 'renamed':
            if not is_results_folder and dest_path:
                # 데이터시트 파일명 변경
                old_filename = os.path.basename(src_path)
                new_filename = os.path.basename(dest_path)

                for datasheet in self.datasheets:
                    if datasheet.datasheet_filename == old_filename:
                        datasheet.datasheet_filename = new_filename
                        break

                self.update_table()

    def refresh_result_viewer_if_selected(self, filename: str):
        """결과 뷰어 새로고침 (DB 저장 후 호출)"""
        # 현재 선택된 항목 확인
        selected_rows = self.table.selectedIndexes()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        if row < 0 or row >= len(self.datasheets):
            return

        datasheet = self.datasheets[row]

        # 현재 선택된 항목이 분석 완료된 항목인지 확인
        if datasheet.datasheet_filename == filename:
            # DB에서 결과 다시 로드
            db_result = self.db.get_analysis_by_filename(datasheet.datasheet_filename)
            if db_result:
                self.result_text.setMarkdown(db_result['analysis_result'])

                # 메타데이터 로드 및 표시
                metadata = self.db.get_metadata(db_result['id'])
                self.update_metadata_table(metadata)

                # 체크포인트 로드 및 표시
                checkpoints = self.db.get_checkpoints_by_datasheet(db_result['id'])
                self.update_checkpoint_list(checkpoints)

                print(f"결과 뷰어 업데이트: {filename}")
            else:
                self.result_text.setPlainText("분석 결과가 없습니다.")
                self.metadata_table.setRowCount(0)
                self.checkpoint_list.setRowCount(0)
                self.python_code_text.clear()

    # ========================================================================
    # Timer & AI Analysis
    # ========================================================================

    def on_analysis_timer(self):
        """타이머: 1분마다 Ready 상태 파일 분석"""
        for datasheet in self.datasheets:
            if datasheet.status == CreatingResultFileStatus.READY:
                # 스레드에서 분석 시작
                thread = Thread(target=self.analyze_datasheet, args=(datasheet,))
                thread.daemon = True
                thread.start()

    def analyze_datasheet(self, datasheet: DataSheetInfo):
        """데이터시트 AI 분석"""
        # 상태 변경: Processing
        datasheet.status = CreatingResultFileStatus.PROCESSING
        self.update_table_signal.emit()

        file_path = os.path.join(self.folder_path, datasheet.datasheet_filename)

        try:
            # PDF를 Base64 이미지로 변환
            ext = os.path.splitext(datasheet.datasheet_filename)[1].lower()

            if ext == '.pdf':
                images = pdf_to_base64_images(file_path, max_pages=5, dpi=150)
            else:
                # 이미지 파일은 직접 Base64 인코딩
                with open(file_path, 'rb') as f:
                    img_bytes = f.read()
                    base64_img = base64.b64encode(img_bytes).decode('utf-8')
                    images = [f"data:image/{ext[1:]};base64,{base64_img}"]

            client = openai.OpenAI(api_key=self.openai_api_key)

            # 1단계: 벤더코드 추출
            print(f"벤더코드 추출 중: {datasheet.datasheet_filename}")
            vendor_messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.VENDORCODE_PROMPT},
                        *[{"type": "image_url", "image_url": {"url": img}} for img in images]
                    ]
                }
            ]
            vendor_response = client.chat.completions.create(
                model="o4-mini",
                messages=vendor_messages
            )
            vendor_code = vendor_response.choices[0].message.content.strip()
            print(f"추출된 벤더코드: {vendor_code}")

            # 2단계: 데이터시트 분석
            print(f"데이터시트 분석 중: {datasheet.datasheet_filename}")
            analysis_messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.ANALYZE_PROMPT},
                        *[{"type": "image_url", "image_url": {"url": img}} for img in images]
                    ]
                }
            ]
            analysis_response = client.chat.completions.create(
                model="o4-mini",
                messages=analysis_messages
            )
            analysis_result = analysis_response.choices[0].message.content

            # 3단계: 태그 생성
            print(f"태그 생성 중: {datasheet.datasheet_filename}")
            tag_messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"분석 결과:\n{analysis_result}\n\n{self.TAG_PROMPT}"}
                    ]
                }
            ]
            tag_response = client.chat.completions.create(
                model="o4-mini",
                messages=tag_messages
            )
            tags_raw = tag_response.choices[0].message.content

            # 코드블럭에서 JSON 추출 (```json ... ``` 또는 ``` ... ```)
            import re
            import json
            code_block_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', tags_raw, re.DOTALL)
            if code_block_match:
                tags_json = code_block_match.group(1).strip()
            else:
                tags_json = tags_raw.strip()

            print(f"생성된 태그: {tags_json[:100]}...")

            # JSON 파싱하여 metadata 딕셔너리 생성
            metadata = {}

            try:
                # JSON 배열 파싱 (작은따옴표를 큰따옴표로 변환)
                tags_json_fixed = tags_json.replace("'", '"')
                tags_array = json.loads(tags_json_fixed)
                if isinstance(tags_array, list):
                    # 각 태그를 Name을 key로, Description을 value로 저장
                    for tag in tags_array:
                        if isinstance(tag, dict) and 'Name' in tag and 'Description' in tag:
                            metadata[tag['Name']] = tag['Description']
                    print(f"태그 파싱 완료: {len(tags_array)}개의 태그")
                else:
                    print("태그가 배열 형식이 아닙니다.")
            except json.JSONDecodeError as e:
                print(f"태그 JSON 파싱 실패: {e}")
                print(f"파싱 시도한 JSON: {tags_json[:200]}...")
                # 파싱 실패 시 원본 저장
                metadata['tags_raw'] = tags_json

            # 4단계: 체크포인트 생성
            print(f"체크포인트 생성 중: {datasheet.datasheet_filename}")
            checkpoint_messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"분석 결과:\n{analysis_result}\n\n{self.CHECKPOINT_PROMPT}"}
                    ]
                }
            ]
            checkpoint_response = client.chat.completions.create(
                model="o4-mini",
                messages=checkpoint_messages
            )
            checkpoints_raw = checkpoint_response.choices[0].message.content

            # 코드블럭에서 JSON 추출
            checkpoint_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', checkpoints_raw, re.DOTALL)
            if checkpoint_match:
                checkpoints_json = checkpoint_match.group(1).strip()
            else:
                checkpoints_json = checkpoints_raw.strip()

            print(f"생성된 체크포인트: {checkpoints_json[:100]}...")

            # 체크포인트 리스트 파싱
            checkpoints_list = []
            try:
                # 작은따옴표를 큰따옴표로 변환
                checkpoints_json_fixed = checkpoints_json.replace("'", '"')
                checkpoints_array = json.loads(checkpoints_json_fixed)
                if isinstance(checkpoints_array, list):
                    checkpoints_list = [str(item) for item in checkpoints_array]
                    print(f"체크포인트 파싱 완료: {len(checkpoints_list)}개")
                else:
                    print("체크포인트가 배열 형식이 아닙니다.")
            except json.JSONDecodeError as e:
                print(f"체크포인트 JSON 파싱 실패: {e}")
                print(f"파싱 시도한 JSON: {checkpoints_json[:200]}...")

            # DB에 저장
            try:
                file_hash = calculate_file_hash(file_path)
                datasheet_id = self.db.insert_analysis(
                    filename=datasheet.datasheet_filename,
                    analysis_result=analysis_result,
                    vendor_code=vendor_code,
                    file_hash=file_hash,
                    metadata=metadata
                )
                print(f"DB 저장 완료: {datasheet.datasheet_filename}")

                # 체크포인트 저장 및 Python 코드 생성
                for idx, checkpoint_text in enumerate(checkpoints_list):
                    try:
                        # 5단계: 각 체크포인트에 대한 Python 코드 생성 (CubicLDRC 실행)
                        print(f"체크포인트 {idx+1}/{len(checkpoints_list)} Python 코드 생성 중...")

                        # 임시 폴더 생성
                        temp_dir = tempfile.gettempdir()
                        ldrc_output_dir = os.path.join(temp_dir, "ldrc")
                        os.makedirs(ldrc_output_dir, exist_ok=True)
                        checkpoint_py_path = os.path.join(ldrc_output_dir, "checkpoint.py")

                        # CubicLDRC 실행 (설정에서 경로 가져오기)
                        cubic_ldrc_exe = self.cubic_ldrc_path
                        python_code_prompt = self._get_python_code_prompt(checkpoint_text, vendor_code)

                        cmd = [
                            cubic_ldrc_exe,
                            "pythonPrompt",
                            "-p", python_code_prompt,
                            "-o", checkpoint_py_path
                        ]

                        print(f"CubicLDRC 실행: {' '.join(cmd)}")
                        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=120)

                        if result.returncode != 0:
                            print(f"CubicLDRC 실행 실패 (코드: {result.returncode})")
                            print(f"stdout: {result.stdout}")
                            print(f"stderr: {result.stderr}")
                            raise Exception(f"CubicLDRC 실행 실패: {result.stderr}")


                        if not os.path.exists(checkpoint_py_path):
                            print(f"checkpoint.py 파일을 찾을 수 없음: {checkpoint_py_path}")
                            raise Exception(f"checkpoint.py 파일이 생성되지 않음")

                        with open(checkpoint_py_path, 'r', encoding='utf-8') as f:
                            python_code = f.read()

                        print(f"Python 코드 읽기 완료 (길이: {len(python_code)}자)")

                        # 체크포인트 저장
                        self.db.insert_checkpoint(
                            datasheet_id=datasheet_id,
                            text=checkpoint_text,
                            python_code=python_code
                        )
                        print(f"체크포인트 {idx+1} 저장 완료")
                    except Exception as e:
                        print(f"체크포인트 저장 실패: {e}")
                        # 오류 발생 시 빈 코드로 저장
                        try:
                            self.db.insert_checkpoint(
                                datasheet_id=datasheet_id,
                                text=checkpoint_text,
                                python_code=""
                            )
                        except:
                            pass

                print(f"체크포인트 저장 완료: {len(checkpoints_list)}개")

            except ValueError as e:
                print(f"DB 저장 실패 (중복 가능): {e}")
            except Exception as e:
                print(f"DB 저장 오류: {e}")

            # 상태 변경: Finish
            datasheet.status = CreatingResultFileStatus.FINISH
            self.update_table_signal.emit()

            # 결과 뷰어 새로고침 (현재 선택된 항목이면 자동 표시)
            self.refresh_result_viewer_signal.emit(datasheet.datasheet_filename)

            print(f"분석 완료: {datasheet.datasheet_filename}")

        except Exception as e:
            print(f"분석 실패: {datasheet.datasheet_filename} - {e}")

            # 상태 복원: Ready (재시도 가능)
            datasheet.status = CreatingResultFileStatus.READY
            self.update_table_signal.emit()

    def cleanup(self):
        """탭이 닫힐 때 정리"""
        self.stop_file_monitoring()


# ============================================================================
# Main Application
# ============================================================================

if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication, QMainWindow

    app = QApplication(sys.argv)

    # 메인 윈도우 생성
    main_window = QMainWindow()
    main_window.setWindowTitle("Data Analyzer")
    main_window.resize(1600, 900)

    # Data Analyzer 탭을 중앙 위젯으로 설정
    tab = DataAnalyzerTab()
    main_window.setCentralWidget(tab)

    # 윈도우 표시
    main_window.show()

    # 프로그램 종료 시 정리
    app.aboutToQuit.connect(tab.cleanup)

    sys.exit(app.exec())
