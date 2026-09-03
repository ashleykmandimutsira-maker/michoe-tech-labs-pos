"""Software-only receipt rendering test; does not require a physical printer."""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QApplication


class PrinterIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_receipt_document_renders_to_pdf(self):
        handle, output_path = tempfile.mkstemp(suffix=".pdf")
        os.close(handle)
        try:
            document = QTextDocument()
            document.setHtml(
                "<h1>Receipt</h1><p>Invoice: PRINT-TEST</p><p>Total: 25.00</p>"
            )
            printer = QPrinter(QPrinter.HighResolution)
            printer.setOutputFormat(QPrinter.PdfFormat)
            printer.setOutputFileName(output_path)
            document.print_(printer)
            self.assertGreater(os.path.getsize(output_path), 0)
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)


if __name__ == "__main__":
    unittest.main()
