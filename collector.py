import logging
import re
import sys
from datetime import datetime
from pathlib import Path

import markdown
import requests
from bs4 import BeautifulSoup
from PyQt5.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QIcon, QIntValidator
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


BASE_DIR = Path(__file__).resolve().parent
RESOURCES_DIR = BASE_DIR / "resources"
RESOURCES_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    filename=str(RESOURCES_DIR / "running.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filemode="a",
)
logging.info("Start collector")

output_file = RESOURCES_DIR / "task_info.md"
html_output_file = BASE_DIR / "task_info.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
    )
}


def normalise_unit_code(unit_code):
    return unit_code.strip().upper()


def semester_to_url_part(semester):
    return "S1C" if semester == "S1" else "S2C"


def build_unit_url(unit_code, year, semester):
    semester_part = semester_to_url_part(semester)
    return f"https://www.sydney.edu.au/units/{unit_code}/{year}-{semester_part}-ND-CC"


def unit_exists_in_outputs(unit_code, md_file, html_file):
    heading_pattern = re.compile(rf"^\s*##\s+{re.escape(unit_code)}\s*$", re.IGNORECASE | re.MULTILINE)
    html_heading_pattern = re.compile(
        rf"<h2>\s*{re.escape(unit_code)}\s*</h2>", re.IGNORECASE
    )

    if md_file.exists() and heading_pattern.search(md_file.read_text(encoding="utf-8")):
        return True

    if html_file.exists() and html_heading_pattern.search(html_file.read_text(encoding="utf-8")):
        return True

    return False


def extract_table_content(html_content, unit_code, md_file):
    soup = BeautifulSoup(html_content, "html.parser")
    table = soup.find("table", id="assessment-table")
    if not table:
        logging.error(f"Cannot find {unit_code} table")
        return False

    thead = table.find("thead")
    if not thead:
        logging.error(f"Cannot find table header for {unit_code}")
        return False

    headers = [th.get_text(strip=True) for th in thead.find_all("th")]
    all_tbody = table.find_all("tbody")
    if not all_tbody:
        logging.error(f"Cannot find tbody for {unit_code}")
        return False

    with md_file.open("a", encoding="utf-8") as f:
        f.write(f"\n## {unit_code}\n\n")
        f.write("| " + " | ".join(headers) + " |\n")
        f.write("| " + " | ".join(["---"] * len(headers)) + " |\n")

        for tbody in all_tbody:
            for row in tbody.find_all("tr", class_="primary"):
                cells = []
                for cell in row.find_all(["th", "td"]):
                    due_date_span = cell.find("span", class_="dueDate")
                    if due_date_span:
                        due_text = due_date_span.get_text(strip=True)
                        match = re.search(r"(\d{2} \w{3} \d{4})", due_text)
                        cells.append(match.group(1) if match else due_text)
                    else:
                        b_tag = cell.find("b")
                        cells.append(
                            b_tag.get_text(strip=True) if b_tag else cell.get_text(strip=True)
                        )

                f.write("| " + " | ".join(cells) + " |\n")

    return True


def convert_markdown_to_html(md_file, html_file):
    if not md_file.exists():
        md_file.write_text("", encoding="utf-8")

    markdown_text = md_file.read_text(encoding="utf-8")
    html_content = markdown.markdown(markdown_text, extensions=["tables"])

    css_style = """
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        h2 { color: #2c3e50; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
        th, td { padding: 10px; border: 1px solid #ddd; text-align: left; }
        th { background-color: #f2f2f2; }
        tr:nth-child(even) { background-color: #f9f9f9; }
    </style>
    """

    full_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Assessment Table</title>
        {css_style}
    </head>
    <body>
        {html_content}
    </body>
    </html>
    """

    html_file.write_text(full_html, encoding="utf-8")
    logging.info(f"Markdown converted to {html_file}")


class ScraperThread(QThread):
    status_changed = pyqtSignal(str)
    result = pyqtSignal(str, str)

    def __init__(self, unit_code, year, semester, md_file, html_file):
        super().__init__()
        self.unit_code = unit_code
        self.year = year
        self.semester = semester
        self.md_file = md_file
        self.html_file = html_file

    def run(self):
        try:
            if unit_exists_in_outputs(self.unit_code, self.md_file, self.html_file):
                self.result.emit(
                    "duplicate",
                    f"{self.unit_code} 已经存在于 task_info.html 中，不会重复提取。",
                )
                return

            self.status_changed.emit("正在检查该学期是否有这门 unit...")
            url = build_unit_url(self.unit_code, self.year, self.semester)
            response = requests.get(url, headers=HEADERS, timeout=15)

            if response.status_code == 404:
                logging.warning(f"Unit {self.unit_code} not found: {url}")
                self.result.emit(
                    "not_found",
                    f"当前学期没有该 unit：{self.unit_code}",
                )
                return

            response.raise_for_status()

            if not BeautifulSoup(response.text, "html.parser").find("table", id="assessment-table"):
                logging.warning(f"Assessment table not found for {self.unit_code}: {url}")
                self.result.emit(
                    "not_found",
                    f"当前学期没有该 unit：{self.unit_code}",
                )
                return

            self.status_changed.emit("正在提取 assessment...")
            if not extract_table_content(response.text, self.unit_code, self.md_file):
                self.result.emit(
                    "error",
                    f"{self.unit_code} 页面存在，但没有找到 assessment table。",
                )
                return

            convert_markdown_to_html(self.md_file, self.html_file)
            logging.info(f"Saved {self.unit_code} assessment into {self.md_file}")
            self.result.emit(
                "success",
                f"{self.unit_code} 提取成功，已写入 task_info.html。",
            )

        except requests.RequestException as e:
            logging.error(f"Request error for {self.unit_code}: {e}")
            self.result.emit("error", f"网络请求失败：{e}")
        except Exception as e:
            logging.exception(f"Unexpected error for {self.unit_code}")
            self.result.emit("error", f"提取失败：{e}")


class YearInput(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.minimum = 2000
        self.maximum = 2100
        self.setObjectName("yearInput")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(44)

        self.text_input = QLineEdit(self)
        self.text_input.setObjectName("yearText")
        self.text_input.setValidator(QIntValidator(self.minimum, self.maximum, self))
        self.text_input.editingFinished.connect(self.normalise_text)

        self.up_button = QToolButton(self)
        self.up_button.setObjectName("yearUpButton")
        self.up_button.setIcon(QIcon(str(RESOURCES_DIR / "spin_up.svg")))
        self.up_button.setAutoRepeat(True)
        self.up_button.clicked.connect(lambda: self.step_by(1))

        self.down_button = QToolButton(self)
        self.down_button.setObjectName("yearDownButton")
        self.down_button.setIcon(QIcon(str(RESOURCES_DIR / "spin_down.svg")))
        self.down_button.setAutoRepeat(True)
        self.down_button.clicked.connect(lambda: self.step_by(-1))

        step_container = QWidget(self)
        step_container.setObjectName("yearStepContainer")
        step_container.setAttribute(Qt.WA_StyledBackground, True)
        step_container.setFixedWidth(32)

        step_layout = QVBoxLayout()
        step_layout.setContentsMargins(0, 0, 0, 0)
        step_layout.setSpacing(0)
        step_layout.addWidget(self.up_button)
        step_layout.addWidget(self.down_button)
        step_container.setLayout(step_layout)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.text_input)
        layout.addWidget(step_container)
        self.setLayout(layout)

    def setRange(self, minimum, maximum):
        self.minimum = minimum
        self.maximum = maximum
        self.text_input.setValidator(QIntValidator(minimum, maximum, self))
        self.setValue(self.value())

    def setValue(self, value):
        value = min(max(int(value), self.minimum), self.maximum)
        self.text_input.setText(str(value))

    def value(self):
        try:
            return int(self.text_input.text())
        except ValueError:
            return self.minimum

    def step_by(self, step):
        self.setValue(self.value() + step)

    def normalise_text(self):
        self.setValue(self.value())


class App(QWidget):
    def __init__(self, md_file, html_file):
        super().__init__()
        self.md_file = md_file
        self.html_file = html_file
        self.scraper_thread = None
        self.init_ui()

    def init_ui(self):
        now = datetime.now()
        if now.month == 1:
            current_year = now.year - 1
            default_semester = "S2"
        elif 2 <= now.month <= 7:
            current_year = now.year
            default_semester = "S1"
        else:
            current_year = now.year
            default_semester = "S2"

        self.setWindowTitle("USYD Assessment Collector")
        icon_path = RESOURCES_DIR / "collector_icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setGeometry(300, 300, 420, 210)
        self.setFixedSize(480, 270)
        chevron_path = (RESOURCES_DIR / "chevron_down.svg").as_posix()
        self.setStyleSheet(
            """
            QWidget {
                background: #f6f8fa;
                color: #1f2937;
                font-size: 14px;
            }
            QLineEdit, QComboBox, #yearInput {
                background: white;
                border: 1px solid #cfd7e3;
                border-radius: 9px;
                min-height: 42px;
                max-height: 42px;
            }
            QLineEdit {
                padding: 0 12px;
            }
            QComboBox {
                padding: 0 38px 0 12px;
            }
            QComboBox::drop-down {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 34px;
                border: none;
                border-top-right-radius: 9px;
                border-bottom-right-radius: 9px;
                background: transparent;
            }
            QComboBox::down-arrow {
                image: url("__CHEVRON_PATH__");
                width: 14px;
                height: 14px;
            }
            #yearText {
                background: transparent;
                border: none;
                border-radius: 0;
                padding: 0 12px;
                min-height: 42px;
                max-height: 42px;
            }
            #yearStepContainer {
                background: transparent;
                border-left: 1px solid #d8e0ea;
                border-top-right-radius: 9px;
                border-bottom-right-radius: 9px;
            }
            #yearUpButton, #yearDownButton {
                background: transparent;
                border: none;
                border-radius: 0;
                min-width: 31px;
                max-width: 31px;
                min-height: 21px;
                max-height: 21px;
                padding: 0;
            }
            #yearUpButton {
                border-bottom: 1px solid #e5eaf0;
            }
            #yearDownButton {
            }
            #yearUpButton:hover, #yearDownButton:hover {
                background: #eef2f7;
            }
            QPushButton {
                background: #f3f4f6;
                border: 1px solid #cfd7e3;
                border-radius: 9px;
                color: #1f2937;
                font-weight: 600;
                min-height: 42px;
                max-height: 42px;
                padding: 0 12px;
            }
            QPushButton:hover {
                background: #e5e7eb;
            }
            QPushButton:disabled {
                background: #eef2f7;
                color: #94a3b8;
            }
            #exitButton {
                border: none;
                background: #d64545;
                color: white;
            }
            #exitButton:hover {
                background: #b93636;
            }
            #statusLabel {
                color: #4b5563;
                min-height: 24px;
            }
            """
            .replace("__CHEVRON_PATH__", chevron_path)
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        input_layout = QGridLayout()
        input_layout.setHorizontalSpacing(12)
        input_layout.setVerticalSpacing(12)
        input_layout.setColumnStretch(0, 1)
        input_layout.setColumnStretch(1, 1)

        self.year_input = YearInput(self)
        self.year_input.setRange(2000, 2100)
        self.year_input.setValue(current_year)
        self.year_input.setToolTip("年份")
        self.year_input.setFixedHeight(44)
        input_layout.addWidget(self.year_input, 0, 0)

        self.semester_input = QComboBox(self)
        self.semester_input.addItems(["S1", "S2"])
        self.semester_input.setCurrentText(default_semester)
        self.semester_input.setToolTip("学期")
        self.semester_input.setFixedHeight(44)
        input_layout.addWidget(self.semester_input, 0, 1)

        self.unit_input = QLineEdit(self)
        self.unit_input.setPlaceholderText("Unit code，例如 AMME2500")
        self.unit_input.returnPressed.connect(self.start_scraping)
        self.unit_input.setFixedHeight(44)
        input_layout.addWidget(self.unit_input, 1, 0, 1, 2)

        layout.addLayout(input_layout)

        self.status_label = QLabel("输入 unit 后点击提取", self)
        self.status_label.setObjectName("statusLabel")
        layout.addWidget(self.status_label)

        button_layout = QGridLayout()
        button_layout.setHorizontalSpacing(12)
        button_layout.setVerticalSpacing(12)
        button_layout.setColumnStretch(0, 1)
        button_layout.setColumnStretch(1, 1)

        self.extract_button = QPushButton("提取", self)
        self.extract_button.setObjectName("extractButton")
        self.extract_button.setFixedHeight(44)
        self.extract_button.clicked.connect(self.start_scraping)
        button_layout.addWidget(self.extract_button, 0, 0)

        self.open_button = QPushButton("打开结果", self)
        self.open_button.setObjectName("openButton")
        self.open_button.setFixedHeight(44)
        self.open_button.clicked.connect(self.open_result)
        button_layout.addWidget(self.open_button, 0, 1)

        self.clear_button = QPushButton("清除结果", self)
        self.clear_button.setObjectName("clearButton")
        self.clear_button.setFixedHeight(44)
        self.clear_button.clicked.connect(self.clear_result)
        button_layout.addWidget(self.clear_button, 1, 0)

        self.exit_button = QPushButton("退出", self)
        self.exit_button.setObjectName("exitButton")
        self.exit_button.setFixedHeight(44)
        self.exit_button.clicked.connect(self.close)
        button_layout.addWidget(self.exit_button, 1, 1)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def start_scraping(self):
        unit_code = normalise_unit_code(self.unit_input.text())
        if not unit_code:
            QMessageBox.warning(self, "缺少 unit", "请先输入 unit code。")
            return

        year = self.year_input.value()
        semester = self.semester_input.currentText()

        self.extract_button.setEnabled(False)
        self.exit_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        self.status_label.setText(f"准备提取 {unit_code} ({year} {semester})...")

        self.scraper_thread = ScraperThread(
            unit_code,
            year,
            semester,
            self.md_file,
            self.html_file,
        )
        self.scraper_thread.status_changed.connect(self.status_label.setText)
        self.scraper_thread.result.connect(self.on_scraper_result)
        self.scraper_thread.start()

    def on_scraper_result(self, status, message):
        self.extract_button.setEnabled(True)
        self.exit_button.setEnabled(True)
        self.open_button.setEnabled(True)
        self.clear_button.setEnabled(True)
        self.status_label.setText(message)

        if status == "success":
            QMessageBox.information(self, "提取成功", message)
        elif status == "duplicate":
            QMessageBox.information(self, "重复 unit", message)
        elif status == "not_found":
            QMessageBox.warning(self, "未找到 unit", message)
        else:
            QMessageBox.critical(self, "提取失败", message)

    def open_result(self):
        if not self.html_file.exists():
            convert_markdown_to_html(self.md_file, self.html_file)

        result_url = QUrl.fromLocalFile(str(self.html_file.resolve()))
        if not QDesktopServices.openUrl(result_url):
            QMessageBox.warning(self, "打开失败", "无法打开 task_info.html。")

    def clear_result(self):
        self.md_file.write_text("", encoding="utf-8")
        convert_markdown_to_html(self.md_file, self.html_file)
        self.status_label.setText("结果已清空")
        QMessageBox.information(self, "清除完成", "task_info.html 已清空。")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    icon_path = RESOURCES_DIR / "collector_icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    ex = App(output_file, html_output_file)
    ex.show()
    sys.exit(app.exec_())
