"""Premium Michoe Tech Labs POS application shell."""
import sys
import logging
import json
import re
import time
from pathlib import Path
from PySide6.QtCore import Qt, QSize, QDate, QStringListModel, QTimer, QObject, QThread, Signal
from PySide6.QtGui import QPixmap, QIcon, QColor, QPainter, QKeySequence, QShortcut
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication,QDialog,QFrame,QGridLayout,QHBoxLayout,QLabel,QLineEdit,QMainWindow,
    QMessageBox,QPushButton,QStackedWidget,QTableWidget,QTableWidgetItem,QVBoxLayout,QHeaderView,
    QAbstractItemView,QAbstractSpinBox,QWidget,QFormLayout,QComboBox,QSpinBox,QDialogButtonBox,QTextEdit,QInputDialog,QToolButton,
    QCheckBox,QScrollArea,QSizePolicy,QDateEdit,QCompleter,QFileDialog)
from PySide6.QtCharts import QChart,QChartView,QValueAxis,QBarSeries,QBarSet,QBarCategoryAxis,QPieSeries
from services.auth_service import AuthenticationService
from services.product_service import ProductService
from services.inventory_service import InventoryService
from services.sales_service import SalesService
from services.customer_service import CustomerService
from services.returns_service import ReturnsService
from services.sync_service import SyncService
from services.spreadsheet_service import SpreadsheetService
from database.db import get_database_manager
from services.permission_service import PermissionService
from services.analytics_service import AnalyticsService
from services.audit_service import AuditService
from models.product import Product
from ui.theme import STYLESHEET,COLORS
from core import clock as system_clock
from core.events import subscribe as subscribe_data_changed
from core.events import emit_change
from services.currency_service import CurrencyService

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)

def configured_currency():
    return CurrencyService().current_code()

def money(value, currency=None):
    return CurrencyService().format_money(value, currency)

def time_greeting():
    hour = system_clock.now().hour
    if hour < 12:
        return 'Good morning'
    if hour < 18:
        return 'Good afternoon'
    return 'Good evening'

def icon(name, color=None):
    path = ROOT / 'assets' / 'icons' / f'{name}.svg'
    if not path.exists(): return QIcon()
    data = path.read_bytes().replace(b'currentColor', (color or COLORS['muted']).encode())
    renderer = QSvgRenderer(data); pix = QPixmap(24, 24); pix.fill(Qt.transparent); painter = QPainter(pix); renderer.render(painter); painter.end(); return QIcon(pix)

def card(title,value,caption,accent=None, icon_name=None):
    f=QFrame(); f.setObjectName('card'); l=QVBoxLayout(f); l.setContentsMargins(16,14,16,14); l.setSpacing(5)
    top=QHBoxLayout(); t=QLabel(title.upper()); t.setObjectName('eyebrow'); top.addWidget(t); top.addStretch()
    if icon_name:
        i=QLabel(); i.setPixmap(icon(icon_name).pixmap(18,18)); top.addWidget(i)
    l.addLayout(top); n=QLabel(value); n.setObjectName('metricValue'); l.addWidget(n); c=QLabel(caption); c.setObjectName('metricCaption'); l.addWidget(c); return f

def panel(title, subtitle=''):
    f=QFrame(); f.setObjectName('panel'); l=QVBoxLayout(f); l.setContentsMargins(16,14,16,16); l.setSpacing(8)
    h=QHBoxLayout(); t=QLabel(title); t.setObjectName('sectionTitle'); h.addWidget(t); h.addStretch()
    if subtitle:
        s=QLabel(subtitle); s.setObjectName('muted'); h.addWidget(s)
    l.addLayout(h); return f,l

def setup_table(table):
    table.setAlternatingRowColors(True); table.setShowGrid(False); table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers); table.verticalHeader().setDefaultSectionSize(34)
    table.horizontalHeader().setStretchLastSection(True); table.setSortingEnabled(False)

class SpreadsheetWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, path, operation, include_cost_price=True, user_id=None):
        super().__init__()
        self.path = path
        self.operation = operation
        self.include_cost_price = include_cost_price
        self.user_id = user_id

    def run(self):
        try:
            service = SpreadsheetService()
            if self.operation == 'export': result = service.export_inventory(self.path, self.include_cost_price)
            elif self.operation == 'import': result = service.import_inventory(self.path, self.user_id)
            else: result = service.generate_template(self.path)
            self.finished.emit(result)
        except Exception as exc:
            logger.exception('Inventory spreadsheet operation failed')
            self.failed.emit(str(exc))

class BulkArchiveWorker(QObject):
    progress = Signal(str)
    finished = Signal(int)
    failed = Signal(str)

    def __init__(self, user_id, reason):
        super().__init__(); self.user_id = user_id; self.reason = reason

    def run(self):
        try:
            self.progress.emit('Preparing...'); self.progress.emit('Archiving...')
            count = ProductService().archive_all_active_products(self.user_id, self.reason)
            self.progress.emit('Completed'); self.finished.emit(count)
        except Exception as exc:
            logger.exception('Bulk archive failed'); self.failed.emit(str(exc))

class CatalogClearWorker(QObject):
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, user_id):
        super().__init__(); self.user_id = user_id

    def run(self):
        try:
            self.progress.emit('Preparing...'); self.progress.emit('Clearing catalog...')
            result = ProductService().clear_active_catalog(self.user_id)
            self.progress.emit('Completed'); self.finished.emit(result)
        except Exception as exc:
            logger.exception('Catalog clear failed'); self.failed.emit(str(exc))

class LoginDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent); self.auth=AuthenticationService(); self.user=None; self.setWindowTitle('Sign in - Online Motor Spares POS'); self.setFixedSize(440,500); self.setStyleSheet(STYLESHEET+'QDialog{background:#FFFFFF;}'); l=QVBoxLayout(self); l.setContentsMargins(42,36,42,30); l.setSpacing(12)
        brand_row=QHBoxLayout(); mark=QLabel(); mark_path=str(__import__('pathlib').Path(__file__).resolve().parent.parent/'assets'/'logo'/'michoe-robot-mark.png'); mark_pix=QPixmap(mark_path)
        if not mark_pix.isNull(): mark.setPixmap(mark_pix.scaled(42,42,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        brand_row.insertWidget(0, mark)
        b=QLabel('MICHOE TECH LABS'); b.setStyleSheet(f"color:{COLORS['primary']};font-size:15px;font-weight:700;letter-spacing:1px;"); brand_row.addWidget(b); brand_row.addStretch(); l.addLayout(brand_row)
        h=QLabel('Online Motor Spares POS'); h.setStyleSheet('font-size:28px;font-weight:700;'); l.addWidget(h); w=QLabel('Welcome back. Sign in to continue.'); w.setObjectName('muted'); l.addWidget(w); l.addSpacing(14)
        self.username=QLineEdit(); self.username.setPlaceholderText('Username'); l.addWidget(self.username)
        password_row=QHBoxLayout(); self.password=QLineEdit(); self.password.setPlaceholderText('Password'); self.password.setEchoMode(QLineEdit.Password); password_row.addWidget(self.password)
        self.password_eye=QToolButton(); self.password_eye.setText('Show'); self.password_eye.setCheckable(True); self.password_eye.setToolTip('Show password'); self.password_eye.clicked.connect(self.toggle_password_visibility); password_row.addWidget(self.password_eye); l.addLayout(password_row)
        self.error=QLabel(''); self.error.setStyleSheet(f"color:{COLORS['danger']};"); l.addWidget(self.error); s=QPushButton('SIGN IN'); s.setObjectName('primary'); s.setMinimumHeight(44); s.clicked.connect(self.login); l.addWidget(s); self.password.returnPressed.connect(self.login); l.addStretch(); foot=QLabel('Offline-first POS system - Powered by Michoe Tech Labs'); foot.setObjectName('muted'); foot.setAlignment(Qt.AlignCenter); l.addWidget(foot); self.username.setFocus()

    def toggle_password_visibility(self, visible):
        self.password.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        self.password_eye.setText('Hide' if visible else 'Show')
        self.password_eye.setToolTip('Hide password' if visible else 'Show password')
    def login(self):
        self.user=self.auth.authenticate(self.username.text().strip(),self.password.text())
        if self.user:self.accept()
        else:self.error.setText('Username or password is incorrect.')

class AuthorizationDialog(QDialog):
    """Re-authenticate an ADMIN for a sensitive product operation."""
    def __init__(self, action, requesting_user_id, permission_code='DELETE_PRODUCT', parent=None):
        super().__init__(parent); self.auth=AuthenticationService(); self.requesting_user_id=requesting_user_id; self.permission_code=permission_code; self.approver=None; self.setWindowTitle('Admin authorization'); self.setMinimumWidth(420); self.setStyleSheet(STYLESHEET); l=QVBoxLayout(self); l.setContentsMargins(28,24,28,24); t=QLabel('Admin authorization'); t.setObjectName('pageTitle'); l.addWidget(t); d=QLabel(f'{action} requires administrator approval.'); d.setObjectName('muted'); l.addWidget(d); self.admin=QLineEdit(); self.admin.setPlaceholderText('Admin username'); l.addWidget(self.admin); self.password=QLineEdit(); self.password.setPlaceholderText('Admin password'); self.password.setEchoMode(QLineEdit.Password); l.addWidget(self.password); self.error=QLabel(''); self.error.setStyleSheet(f'color:{COLORS["danger"]};'); l.addWidget(self.error); b=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); b.accepted.connect(self.verify); b.rejected.connect(self.reject); l.addWidget(b)
    def verify(self):
        user=self.auth.authenticate(self.admin.text().strip(),self.password.text())
        if not user or not user.is_admin() or not user.has_permission(self.permission_code):
            self.error.setText('Valid administrator credentials are required.'); return
        self.approver=user; self.accept()

class DashboardPage(QWidget):
    def __init__(self,products,user):
        super().__init__(); self.products=products; self.user=user; self.analytics=AnalyticsService(); self.sync=SyncService()
        outer=QVBoxLayout(self); outer.setContentsMargins(28,22,28,28); outer.setSpacing(14)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); scroll.setStyleSheet(f"background:{COLORS['canvas']};border:0;"); outer.addWidget(scroll)
        body=QWidget(); body.setStyleSheet(f"background:{COLORS['canvas']};"); scroll.setWidget(body); l=QVBoxLayout(body); l.setContentsMargins(0,0,8,0); l.setSpacing(14)
        self.greeting=QLabel(); self.greeting.setObjectName('pageTitle'); l.addWidget(self.greeting)
        s=QLabel("A live view of sales, stock and operational health."); s.setObjectName('muted'); l.addWidget(s)
        self.period=QComboBox(); self.period.addItem('Today','today'); self.period.addItem('This week','week'); self.period.addItem('This month','month'); self.period.addItem('This year','year'); self.period.addItem('Custom range','custom'); self.period.currentIndexChanged.connect(self.refresh)
        self.custom_start=QDateEdit(QDate.currentDate()); self.custom_start.setCalendarPopup(True); self.custom_start.setDisplayFormat('dd MMM yyyy'); self.custom_start.dateChanged.connect(self.refresh); self.custom_start.setVisible(False)
        self.custom_end=QDateEdit(QDate.currentDate()); self.custom_end.setCalendarPopup(True); self.custom_end.setDisplayFormat('dd MMM yyyy'); self.custom_end.dateChanged.connect(self.refresh); self.custom_end.setVisible(False)
        ph=QHBoxLayout(); ph.addWidget(QLabel('Reporting period')); ph.addWidget(self.period); ph.addWidget(self.custom_start); ph.addWidget(self.custom_end); ph.addStretch(); l.addLayout(ph)
        self.kpis=QGridLayout(); self.kpis.setSpacing(10); l.addLayout(self.kpis)
        row=QHBoxLayout(); row.setSpacing(14); l.addLayout(row)
        top_panel,top_layout=panel('Top selling parts','This year'); self.top_table=QTableWidget(0,4); self.top_table.setHorizontalHeaderLabels(['Part','Units','Revenue','Profit']); self.top_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); setup_table(self.top_table); top_layout.addWidget(self.top_table); row.addWidget(top_panel,3)
        inv_panel,inv_layout=panel('Inventory health','Active catalog'); self.inv_grid=QGridLayout(); inv_layout.addLayout(self.inv_grid); low=QLabel('Low stock watchlist'); low.setObjectName('sectionTitle'); inv_layout.addWidget(low); self.low_table=QTableWidget(0,3); self.low_table.setHorizontalHeaderLabels(['Product','Stock','Status']); self.low_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); setup_table(self.low_table); self.low_table.setMaximumHeight(210); inv_layout.addWidget(self.low_table); row.addWidget(inv_panel,2)
        analytics_row=QHBoxLayout(); analytics_row.setSpacing(14); l.addLayout(analytics_row)
        brand_panel,brand_layout=panel('Sales by brand','This year'); self.brand_chart=QChartView(); self.brand_chart.setMinimumHeight(220); brand_layout.addWidget(self.brand_chart); analytics_row.addWidget(brand_panel,1)
        payment_panel,payment_layout=panel('Payment mix','This year'); self.payment_chart=QChartView(); self.payment_chart.setMinimumHeight(220); payment_layout.addWidget(self.payment_chart); analytics_row.addWidget(payment_panel,1)
        vehicle_panel,vehicle_layout=panel('Sales by vehicle','Select a make and model'); self.vehicle_controls=QHBoxLayout(); self.vehicle_make=QComboBox(); self.vehicle_model=QComboBox(); self.vehicle_make.currentIndexChanged.connect(self.refresh_vehicle_models); self.vehicle_model.currentIndexChanged.connect(self.refresh_vehicles); self.vehicle_controls.addWidget(self.vehicle_make); self.vehicle_controls.addWidget(self.vehicle_model); vehicle_layout.addLayout(self.vehicle_controls); self.vehicle_table=QTableWidget(0,3); self.vehicle_table.setHorizontalHeaderLabels(['Vehicle','Units','Revenue']); self.vehicle_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); setup_table(self.vehicle_table); vehicle_layout.addWidget(self.vehicle_table); analytics_row.addWidget(vehicle_panel,1)
        recent_panel,recent_layout=panel('Recent transactions','Latest completed sales'); self.recent_table=QTableWidget(0,5); self.recent_table.setHorizontalHeaderLabels(['Invoice','Customer','Cashier','Amount','Status']); self.recent_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); setup_table(self.recent_table); recent_layout.addWidget(self.recent_table); l.addWidget(recent_panel)
        sync_panel,sync_layout=panel('Synchronization status','Offline-first operations'); sync_row=QHBoxLayout(); self.sync_status=QLabel('ONLINE - LOCAL DATABASE'); self.sync_status.setObjectName('statusOnline'); sync_row.addWidget(self.sync_status); sync_row.addStretch(); self.sync_last=QLabel(); self.sync_last.setObjectName('muted'); sync_row.addWidget(self.sync_last); sync_layout.addLayout(sync_row); self.sync_detail=QLabel(); self.sync_detail.setObjectName('muted'); sync_layout.addWidget(self.sync_detail)
        clock_row=QHBoxLayout(); clock_label=QLabel('System clock (this PC)'); clock_label.setObjectName('muted'); clock_row.addWidget(clock_label); self.system_clock_value=QLabel(); self.system_clock_value.setObjectName('metricCaption'); clock_row.addWidget(self.system_clock_value); clock_row.addStretch(); self.dashboard_refreshed=QLabel(); self.dashboard_refreshed.setObjectName('muted'); clock_row.addWidget(self.dashboard_refreshed); sync_layout.addLayout(clock_row)
        l.addWidget(sync_panel)
        self._clock_timer=QTimer(self); self._clock_timer.setInterval(1000); self._clock_timer.timeout.connect(self._tick_clock); self._clock_timer.start(); self._tick_clock()
        self.refresh()

    def _tick_clock(self):
        self.system_clock_value.setText(system_clock.display_str())
        first_name = self.user.full_name.split()[0] if self.user and self.user.full_name else 'there'
        self.greeting.setText(f'{time_greeting()}, {first_name}')

    def period_args(self):
        p=self.period.currentData() or 'today'; custom=(self.custom_start.date().toString('yyyy-MM-dd'),self.custom_end.date().toString('yyyy-MM-dd')) if p == 'custom' else (None,None); return p,*custom

    def refresh(self):
        p,start,end=self.period_args(); self.custom_start.setVisible(p == 'custom'); self.custom_end.setVisible(p == 'custom'); summary=self.analytics.get_sales_summary(p,start,end); inv=self.analytics.get_inventory_summary()
        self.dashboard_refreshed.setText(f"Dashboard updated: {system_clock.display_str()}")
        while self.kpis.count():
            item=self.kpis.takeAt(0); item.widget().deleteLater() if item.widget() else None
        values=[("Today's sales",money(summary['revenue']),f"{summary['transactions']} transactions",'chart'),('Profit',money(summary['profit']),'Gross profit estimate','analytics'),('Units sold',str(summary['units_sold']),'Items leaving stock','package'),('Average sale',money(summary['average_transaction']),'Average transaction value','invoice'),('Low stock',str(inv['low_stock']),'Needs attention','warning'),('Out of stock',str(inv['out_of_stock']),'Immediate reorder','error'),('Returns',str(summary['returns']),'Period total','return'),('Inventory value',money(inv['stock_selling_value']),'Selling value','package')]
        for i,(a,b,c,ic) in enumerate(values): self.kpis.addWidget(card(a,b,c,icon_name=ic if (ROOT/'assets'/'icons'/f'{ic}.svg').exists() else 'chart'),i//4,i%4)
        while self.inv_grid.count():
            item=self.inv_grid.takeAt(0); item.widget().deleteLater() if item.widget() else None
        for i,(label,value) in enumerate([('Products',inv['total_products']),('Units in stock',inv['units_in_stock']),('Cost value',money(inv['stock_cost_value'])),('Potential profit',money(inv['potential_profit']))]):
            self.inv_grid.addWidget(QLabel(label),i,0); v=QLabel(str(value)); v.setObjectName('metricValue'); self.inv_grid.addWidget(v,i,1)
        sync_status=self.sync.get_sync_status(); last=self.sync.db.execute_query("SELECT MAX(synced_at) last_sync FROM sync_queue WHERE status='SYNCED'")[0]['last_sync']; self.sync_last.setText(f"Last sync: {last or 'Not yet'}"); self.sync_detail.setText(f"Pending uploads: {sync_status['PENDING']}   |   Synced: {sync_status['SYNCED']}   |   Failed: {sync_status['FAILED']}")
        self.top_table.setRowCount(0)
        for r,x in enumerate(self.analytics.get_top_products(p,10,start,end)):
            self.top_table.insertRow(r); [self.top_table.setItem(r,c,QTableWidgetItem(str(v))) for c,v in enumerate([f"{x['part_no']} - {x['description']}",str(x['quantity_sold']),money(x['revenue']),money(x['profit'])])]
        low=self.analytics.get_low_stock_products(); self.low_table.setRowCount(len(low))
        for r,x in enumerate(low):
            for c,v in enumerate([x['description'],str(x['current_stock']),x['status']]): self.low_table.setItem(r,c,QTableWidgetItem(v))
        all_vehicles=self.analytics.get_vehicle_sales(p,start=start,end=end); self.vehicle_make.blockSignals(True); current_make=self.vehicle_make.currentData(); self.vehicle_make.clear(); self.vehicle_make.addItem('All makes','');
        for make in sorted({x['make'] for x in all_vehicles}): self.vehicle_make.addItem(make,make)
        if current_make is not None:
            idx=self.vehicle_make.findData(current_make); self.vehicle_make.setCurrentIndex(idx if idx >= 0 else 0)
        self.vehicle_make.blockSignals(False); self.refresh_vehicle_models(); self.refresh_vehicles()
        recent=self.analytics.get_recent_transactions(); self.recent_table.setRowCount(len(recent))
        for r,x in enumerate(recent):
            for c,v in enumerate([x['invoice'],x['customer'],x['cashier'],money(x['amount']),x['status']]): self.recent_table.setItem(r,c,QTableWidgetItem(str(v)))
        self.refresh_breakdowns(p,start,end)

    def refresh_breakdowns(self,p,start=None,end=None):
        brands=self.analytics.get_brand_sales(p,start=start,end=end); bchart=QChart(); bchart.setBackgroundVisible(False); bchart.legend().hide(); bs=QBarSeries(); bs.setLabelsVisible(True); bar=QBarSet('Revenue'); bar.setColor(QColor(COLORS['primary'])); [bar.append(float(x['revenue'])) for x in brands]; bs.append(bar); bchart.addSeries(bs); bx=QBarCategoryAxis(); bx.append([x['brand'] for x in brands]); bchart.addAxis(bx,Qt.AlignBottom); by=QValueAxis(); by.setRange(0,max([float(x['revenue']) for x in brands] or [1])*1.2); bchart.addAxis(by,Qt.AlignLeft); bs.attachAxis(bx); bs.attachAxis(by); self.brand_chart.setChart(bchart)
        payments=self.analytics.get_payment_method_sales(p,start,end); pchart=QChart(); pchart.setBackgroundVisible(False); ps=QPieSeries(); [ps.append(x['method'].replace('_',' '),float(x['amount'])) for x in payments]; pchart.addSeries(ps); pchart.legend().setVisible(bool(payments)); self.payment_chart.setChart(pchart)

    def refresh_vehicle_models(self):
        p,start,end=self.period_args(); make=self.vehicle_make.currentData() or ''; all_vehicles=self.analytics.get_vehicle_sales(p,make=make,start=start,end=end); current=self.vehicle_model.currentData(); self.vehicle_model.blockSignals(True); self.vehicle_model.clear(); self.vehicle_model.addItem('All models','');
        for model in sorted({x['model'] for x in all_vehicles}): self.vehicle_model.addItem(model,model)
        idx=self.vehicle_model.findData(current); self.vehicle_model.setCurrentIndex(idx if idx >= 0 else 0); self.vehicle_model.blockSignals(False)
        self.refresh_vehicles()

    def refresh_vehicles(self):
        p,start,end=self.period_args(); make=self.vehicle_make.currentData() or ''; model=self.vehicle_model.currentData() or ''; vehicles=self.analytics.get_vehicle_sales(p,make=make,model=model,start=start,end=end)[:8]; self.vehicle_table.setRowCount(len(vehicles))
        for r,x in enumerate(vehicles):
            for c,v in enumerate([f"{x['make']} {x['model']}",str(x['quantity_sold']),money(x['revenue'])]): self.vehicle_table.setItem(r,c,QTableWidgetItem(v))

class CustomerDialog(QDialog):
    """Collect buyer details before payment and attach them to the invoice."""
    def __init__(self, sales, parent=None, current=None):
        super().__init__(parent)
        self.sales = sales
        self.setWindowTitle('Customer details')
        self.setMinimumWidth(520)
        self.setStyleSheet(STYLESHEET)
        current = current or {}
        l = QVBoxLayout(self)
        title = QLabel('Customer / Buyer')
        title.setObjectName('pageTitle')
        l.addWidget(title)
        sub = QLabel('These details will appear on the invoice and remain linked to the sale.')
        sub.setObjectName('muted')
        l.addWidget(sub)
        form = QFormLayout()
        self.name = QLineEdit(current.get('name', ''))
        self.name.setPlaceholderText('Customer name (required for a named invoice)')
        self.phone = QLineEdit(current.get('phone', ''))
        self.phone.setPlaceholderText('Phone / contact number')
        self.email = QLineEdit(current.get('email', ''))
        self.email.setPlaceholderText('Email address')
        self.city = QLineEdit(current.get('city', ''))
        self.city.setPlaceholderText('City')
        self.vehicle_make = QLineEdit(current.get('vehicle_make', ''))
        self.vehicle_make.setPlaceholderText('e.g. Toyota')
        self.vehicle_model = QLineEdit(current.get('vehicle_model', ''))
        self.vehicle_model.setPlaceholderText('e.g. Corolla')
        self.registration = QLineEdit(current.get('vehicle_registration', ''))
        self.registration.setPlaceholderText('Vehicle registration')
        form.addRow('Customer name *', self.name)
        form.addRow('Phone / contact', self.phone)
        form.addRow('Email', self.email)
        form.addRow('City', self.city)
        form.addRow('Vehicle make', self.vehicle_make)
        form.addRow('Vehicle model', self.vehicle_model)
        form.addRow('Registration', self.registration)
        l.addLayout(form)
        self.error = QLabel('')
        self.error.setStyleSheet(f"color:{COLORS['danger']};")
        l.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        l.addWidget(buttons)
        self.name.setFocus()

    def accept(self):
        if not self.name.text().strip():
            self.error.setText('Customer name is required for a named invoice.')
            return
        super().accept()

    def values(self):
        return {
            'name': self.name.text().strip(),
            'phone': self.phone.text().strip() or None,
            'email': self.email.text().strip() or None,
            'city': self.city.text().strip() or None,
            'vehicle_make': self.vehicle_make.text().strip() or None,
            'vehicle_model': self.vehicle_model.text().strip() or None,
            'vehicle_registration': self.registration.text().strip() or None,
        }


class PaymentDialog(QDialog):
    """Payment confirmation with method, tendered amount and change."""
    def __init__(self, total, parent=None):
        super().__init__(parent)
        self.total = float(total)
        self.currency = configured_currency()
        self.setWindowTitle('Take payment')
        self.setMinimumWidth(460)
        self.setStyleSheet(STYLESHEET)
        l = QVBoxLayout(self)
        title = QLabel('Payment')
        title.setObjectName('pageTitle')
        l.addWidget(title)
        amount = QLabel(money(self.total, self.currency))
        self.amount_label = amount
        amount.setObjectName('metricValue')
        l.addWidget(amount)
        form = QFormLayout()
        self.method = QComboBox()
        self.method.addItem('Cash USD', 'CASH_USD')
        self.method.addItem('Cash ZiG', 'CASH_ZIG')
        self.method.addItem('EcoCash', 'ECOCASH')
        self.method.addItem('Card', 'CARD')
        self.method.addItem('Store credit', 'STORE_CREDIT')
        self.tendered = QLineEdit()
        self.tendered.setPlaceholderText(f'Enter amount received (minimum {money(self.total, self.currency)})')
        self.tendered.setText(f'{self.total:.2f}')
        self.change = QLabel(money(0, self.currency))
        self.change.setObjectName('metricCaption')
        form.addRow('Payment method', self.method)
        form.addRow('Amount tendered', self.tendered)
        form.addRow('Change', self.change)
        l.addLayout(form)
        self.payments = []
        self.payments_table = QTableWidget(0, 3); self.payments_table.setHorizontalHeaderLabels(['Method', 'Amount', 'Currency']); self.payments_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); self.payments_table.setMaximumHeight(130)
        l.addWidget(self.payments_table)
        add_payment = QPushButton('Add payment portion'); add_payment.setIcon(icon('plus')); add_payment.clicked.connect(self.add_payment_portion); l.addWidget(add_payment)
        self.error = QLabel('')
        self.error.setStyleSheet(f"color:{COLORS['danger']};")
        l.addWidget(self.error)
        self.tendered.textChanged.connect(self.update_change)
        self.method.currentIndexChanged.connect(self.update_currency)
        self.update_currency()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        l.addWidget(buttons)
        self.update_change()

    def update_change(self):
        try:
            tendered = float(self.tendered.text().strip())
            self.change.setText(money(max(0.0, tendered - self.total), self.currency))
        except ValueError:
            self.change.setText(money(0, self.currency))

    def update_currency(self):
        method = self.method.currentData()
        self.currency = {'CASH_USD': 'USD', 'CASH_ZIG': 'ZiG'}.get(method, configured_currency())
        self.amount_label.setText(f'Total due: {money(self.total, self.currency)}')
        self.tendered.setPlaceholderText(f'Enter amount received (minimum {money(self.total, self.currency)})')
        self.update_change()

    def accept(self):
        try:
            tendered = float(self.tendered.text().strip())
        except ValueError:
            self.error.setText('Enter a valid payment amount.')
            return
        method = self.method.currentData()
        if method == 'STORE_CREDIT':
            tendered = self.total
        if not self.payments:
            self.add_payment_portion()
        paid = sum(payment['amount'] for payment in self.payments)
        if paid < self.total - 0.005:
            self.error.setText(f'Payment is short by {money(self.total - paid, self.currency)}.')
            return
        super().accept()

    def add_payment_portion(self):
        try: tendered = float(self.tendered.text().strip())
        except ValueError: self.error.setText('Enter a valid payment amount.'); return
        method = self.method.currentData(); remaining = max(0.0, self.total - sum(payment['amount'] for payment in self.payments)); amount = self.total if method == 'STORE_CREDIT' else min(tendered, remaining)
        if amount <= 0: self.error.setText('No balance remains to add.'); return
        self.payments.append({'method': method, 'amount': amount, 'currency': self.currency, 'tendered': tendered if method.startswith('CASH') else amount})
        row = self.payments_table.rowCount(); self.payments_table.insertRow(row)
        for column, value in enumerate([method.replace('_', ' '), money(amount, self.currency), self.currency]): self.payments_table.setItem(row, column, QTableWidgetItem(value))
        remaining = max(0.0, self.total - sum(payment['amount'] for payment in self.payments)); self.tendered.setText(f'{remaining:.2f}'); self.error.setText(f'Remaining balance: {money(remaining, self.currency)}')


class QuantityDialog(QDialog):
    """Ask for a quantity before adding or updating a cart item."""
    def __init__(self, product, available, current=0, mode='add', parent=None):
        super().__init__(parent)
        self.product = product
        self.available = int(max(0, available))
        self.current = int(max(0, current))
        self.mode = mode
        self.setWindowTitle('Select quantity')
        self.setMinimumWidth(430)
        self.setStyleSheet(STYLESHEET)

        l = QVBoxLayout(self)
        title = QLabel('Select quantity')
        title.setObjectName('pageTitle')
        l.addWidget(title)
        info = QLabel(f'{product.part_no} — {product.description}')
        info.setObjectName('sectionTitle')
        l.addWidget(info)
        stock = QLabel(f'Available stock: {self.available} | Current in cart: {self.current}')
        stock.setObjectName('muted')
        l.addWidget(stock)

        form = QFormLayout()
        self.quantity = QSpinBox()
        self.quantity.setObjectName('quantitySpinBox')
        self.quantity.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
        self.quantity.setMinimum(1)
        self.quantity.setMaximum(max(1, self.available if mode == 'add' else self.available))
        self.quantity.setValue(1 if mode == 'add' else max(1, self.current))
        self.quantity.setMinimumHeight(46)
        self.quantity.setMinimumWidth(220)
        self.quantity.setAccelerated(True)
        self.quantity.lineEdit().setAlignment(Qt.AlignCenter)
        form.addRow('Quantity', self.quantity)
        l.addLayout(form)

        self.summary = QLabel()
        self.summary.setObjectName('metricCaption')
        l.addWidget(self.summary)
        self.quantity.valueChanged.connect(self.update_summary)
        self.update_summary()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Add to cart' if mode == 'add' else 'Update quantity')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        l.addWidget(buttons)

    def update_summary(self):
        qty = self.quantity.value()
        self.summary.setText(f'Line value: {money(qty * float(self.product.selling_price), self.product.currency)}')

    def accept(self):
        qty = self.quantity.value()
        if qty < 1:
            return
        if self.mode == 'add' and self.current + qty > self.available:
            QMessageBox.warning(self, 'Insufficient stock', f'Only {self.available} units are available. You already have {self.current} in the cart.')
            return
        if self.mode == 'set' and qty > self.available:
            QMessageBox.warning(self, 'Insufficient stock', f'Only {self.available} units are available.')
            return
        self.selected_quantity = qty
        super().accept()


class POSPage(QWidget):
    def __init__(self, products, inventory, user):
        super().__init__()
        self.products = products
        self.inventory = inventory
        self.user = user
        self.sales = SalesService()
        self.crm = CustomerService()
        self.cart = {}
        self.customer = None
        self.selected_vehicle = None
        self.recent_identifiers = self._load_recent_identifiers()

        l = QVBoxLayout(self)
        l.setContentsMargins(28, 24, 28, 24)
        l.setSpacing(12)
        h = QHBoxLayout()
        t = QLabel('Point of Sale')
        t.setObjectName('pageTitle')
        h.addWidget(t)
        h.addStretch()
        self.customer_label = QLabel('Walk-in customer')
        self.customer_label.setObjectName('muted')
        h.addWidget(self.customer_label)
        customer_btn = QPushButton('Customer')
        customer_btn.setIcon(icon('customer'))
        customer_btn.clicked.connect(self.edit_customer)
        h.addWidget(customer_btn)
        select_customer_btn = QPushButton('Select customer'); select_customer_btn.setIcon(icon('search')); select_customer_btn.clicked.connect(self.select_customer); h.addWidget(select_customer_btn)
        select_vehicle_btn = QPushButton('Select vehicle'); select_vehicle_btn.setIcon(icon('package')); select_vehicle_btn.clicked.connect(self.select_vehicle); h.addWidget(select_vehicle_btn)
        l.addLayout(h)

        search_row = QHBoxLayout()
        self.scan = QLineEdit()
        self.scan.setPlaceholderText('Scan barcode, enter Part No. or Product ID')
        self.scan.setMinimumHeight(44)
        self.scan.returnPressed.connect(self.scan_product)
        search_row.addWidget(self.scan, 1)
        clear_search = QPushButton('Clear')
        clear_search.clicked.connect(lambda: (self.scan.clear(), self.search('')))
        search_row.addWidget(clear_search)
        l.addLayout(search_row)

        # Visible customer/invoice context: customer details are part of the POS
        # transaction, not hidden behind the payment workflow.
        customer_panel = QFrame()
        customer_panel.setObjectName('card')
        customer_layout = QHBoxLayout(customer_panel)
        customer_layout.setContentsMargins(16, 12, 16, 12)
        customer_layout.setSpacing(14)
        customer_icon = QLabel()
        customer_icon.setPixmap(icon('customer').pixmap(24, 24))
        customer_layout.addWidget(customer_icon)
        customer_text = QVBoxLayout()
        customer_title = QLabel('CUSTOMER / BUYER')
        customer_title.setObjectName('eyebrow')
        customer_text.addWidget(customer_title)
        self.customer_detail = QLabel('Walk-in customer | No vehicle details captured')
        self.customer_detail.setObjectName('muted')
        self.customer_detail.setWordWrap(True)
        customer_text.addWidget(self.customer_detail)
        customer_layout.addLayout(customer_text, 1)
        self.invoice_status = QLabel('Invoice: created after payment')
        self.invoice_status.setObjectName('muted')
        customer_layout.addWidget(self.invoice_status)
        customer_edit = QPushButton('Add / Edit customer')
        customer_edit.setIcon(icon('edit'))
        customer_edit.clicked.connect(self.edit_customer)
        customer_layout.addWidget(customer_edit)
        l.addWidget(customer_panel)

        self.recent_model = QStringListModel(self.recent_identifiers, self)
        self.completer = QCompleter(self.recent_model, self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.scan.setCompleter(self.completer)
        for key, handler in (("F2", lambda: self.scan.setFocus()), ("F4", self.edit_customer),
                             ("F6", self.change_selected_quantity), ("F8", self.payment),
                             ("F9", self.create_quote), ("ESC", self.clear_cart),
                             ("Ctrl+Return", self.add_selected), ("Delete", self.remove_selected)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(handler)

        cols = QHBoxLayout()
        cols.setSpacing(16)
        l.addLayout(cols, 1)
        left = QFrame()
        left.setObjectName('panel')
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel('PRODUCT SEARCH'))
        self.results = QTableWidget(0, 6)
        self.results.setHorizontalHeaderLabels(['Part No', 'Description', 'Brand', 'Vehicle', 'Price', 'Stock'])
        self.results.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results.setSortingEnabled(False)
        self.results.doubleClicked.connect(self.add_selected)
        self.results.itemActivated.connect(lambda _item: self.add_selected())
        ll.addWidget(self.results, 1)
        result_actions = QHBoxLayout()
        add_product_btn = QPushButton('Add to cart')
        add_product_btn.setObjectName('primary')
        add_product_btn.setIcon(icon('plus'))
        add_product_btn.clicked.connect(self.add_selected)
        result_actions.addWidget(add_product_btn)
        result_actions.addStretch()
        ll.addLayout(result_actions)
        cols.addWidget(left, 3)

        right = QFrame()
        right.setObjectName('panel')
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel('CART'))
        self.cart_table = QTableWidget(0, 7)
        self.cart_table.setHorizontalHeaderLabels(['Part No', 'Description', 'Brand', 'Vehicle', 'Qty', 'Unit Price', 'Line Total'])
        self.cart_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cart_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        setup_table(self.cart_table)
        self.cart_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cart_table.itemActivated.connect(lambda _item: self.change_selected_quantity())
        rl.addWidget(self.cart_table, 1)
        action_row = QHBoxLayout()
        change_qty = QPushButton('Change quantity')
        change_qty.setIcon(icon('edit'))
        change_qty.clicked.connect(self.change_selected_quantity)
        remove = QPushButton('Delete selected')
        remove.setIcon(icon('delete'))
        remove.clicked.connect(self.remove_selected)
        clear = QPushButton('Clear cart')
        clear.clicked.connect(self.clear_cart)
        action_row.addWidget(change_qty)
        action_row.addWidget(remove)
        action_row.addWidget(clear)
        action_row.addStretch()
        rl.addLayout(action_row)
        total_row = QHBoxLayout()
        total_row.addWidget(QLabel('TOTAL'))
        total_row.addStretch()
        self.total = QLabel(money(0))
        self.total.setObjectName('metricValue')
        total_row.addWidget(self.total)
        rl.addLayout(total_row)
        pay = QPushButton('TAKE PAYMENT')
        pay.setObjectName('primary')
        pay.setMinimumHeight(44)
        pay.clicked.connect(self.payment)
        rl.addWidget(pay)
        self.print_receipt_btn = QPushButton('PRINT RECEIPT')
        self.print_receipt_btn.setIcon(icon('print'))
        self.print_receipt_btn.setEnabled(False)
        self.print_receipt_btn.clicked.connect(self.print_receipt)
        rl.addWidget(self.print_receipt_btn)
        held_row = QHBoxLayout()
        hold = QPushButton('PARK SALE'); hold.setIcon(icon('save')); hold.clicked.connect(self.hold_sale); held_row.addWidget(hold)
        resume = QPushButton('RESUME HELD'); resume.setIcon(icon('refresh')); resume.clicked.connect(self.resume_held_sale); held_row.addWidget(resume)
        rl.addLayout(held_row)
        quote = QPushButton('CREATE QUOTATION')
        quote.setIcon(icon('invoice'))
        quote.clicked.connect(self.create_quote)
        rl.addWidget(quote)
        quote_history = QPushButton('QUOTATION HISTORY'); quote_history.setIcon(icon('invoice')); quote_history.clicked.connect(self.quotation_history)
        rl.addWidget(quote_history)
        cols.addWidget(right, 2)
        self.search('')
        self.scan.setFocus()

    def _load_recent_identifiers(self):
        try:
            row = self.sales.db.execute_query("SELECT value FROM settings WHERE key='pos_recent_identifiers' LIMIT 1")
            if row and row[0]['value']:
                import json
                values = json.loads(row[0]['value'])
                return [str(x) for x in values if str(x).strip()][:20]
        except Exception:
            pass
        return []

    def _remember_identifier(self, value):
        value = str(value).strip()
        if not value:
            return
        self.recent_identifiers = [value] + [x for x in self.recent_identifiers if x != value]
        self.recent_identifiers = self.recent_identifiers[:20]
        self.recent_model.setStringList(self.recent_identifiers)
        try:
            import json
            self.sales.db.execute_update("INSERT INTO settings (key,value,data_type) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP", ("pos_recent_identifiers", json.dumps(self.recent_identifiers), 'json'))
        except Exception:
            pass

    def search(self, text):
        text = (text or '').strip()
        if text.upper().startswith('ID:') and text[3:].strip().isdigit():
            p = self.products.get_product_by_id(int(text[3:].strip()))
            if p and not p.active:
                p = None
            items = [p] if p else []
        else:
            p = self.products.get_product_by_barcode(text) or self.products.get_product_by_part_no(text) if text else None
            items = [p] if p else (self.products.search_products(text) if text else self.products.get_all_products())
        self.results.setRowCount(len(items))
        if not items:
            self.results.setRowCount(1)
            self.results.setItem(0, 0, QTableWidgetItem('No products found.'))
            self.results.setSpan(0, 0, 1, 6)
            return
        for r, p in enumerate(items):
            part_item = QTableWidgetItem(p.part_no)
            part_item.setData(Qt.UserRole, p.id)
            self.results.setItem(r, 0, part_item)
            for c, v in enumerate([p.description, p.brand or '', f'{p.vehicle_make or ""} {p.vehicle_model or ""}'.strip(), money(p.selling_price, p.currency), str(p.quantity_on_hand)], start=1):
                self.results.setItem(r, c, QTableWidgetItem(v))

    def refresh(self):
        """Reload search results without touching the in-progress cart."""
        self.search(self.scan.text())
        self.refresh_cart()

    def scan_product(self):
        term = self.scan.text().strip()
        if not term:
            return
        self._remember_identifier(term)
        p = None
        p = self.products.get_product_by_barcode(term) or self.products.get_product_by_part_no(term)
        if not p and term.upper().startswith('ID:') and term[3:].strip().isdigit():
            p = self.products.get_product_by_id(int(term[3:].strip()))
            if p and not p.active:
                p = None
        if p:
            if p.id in self.cart:
                current = int(self.cart[p.id]['quantity'])
                if current >= int(p.quantity_on_hand):
                    QMessageBox.warning(self, 'Insufficient stock', f'Only {p.quantity_on_hand} units are available for {p.description}.')
                else:
                    self.cart[p.id]['quantity'] = current + 1
                    self.refresh_cart()
                self.scan.clear()
            elif self.add_to_cart(p):
                self.scan.clear()
        else:
            self.search(term)

    def add_selected(self):
        r = self.results.currentRow()
        if r < 0:
            QMessageBox.information(self, 'Select a product', 'Select a product from the search results first.')
            return False
        part_item = self.results.item(r, 0)
        product_id = part_item.data(Qt.UserRole) if part_item else None
        p = self.products.get_product_by_id(product_id) if product_id is not None else None
        if not p:
            QMessageBox.warning(self, 'Product not found', 'The selected product could not be loaded.')
            return False
        self._remember_identifier(p.part_no)
        added = self.add_to_cart(p)
        self.scan.setFocus()
        return added

    def add_to_cart(self, product):
        available = int(product.quantity_on_hand)
        if available <= 0:
            QMessageBox.warning(self, 'Out of stock', f'{product.description} is out of stock.')
            return False

        current_qty = int(self.cart.get(product.id, {}).get('quantity', 0))
        dialog = QuantityDialog(product, available, current=current_qty, mode='add', parent=self)
        if dialog.exec() != QDialog.Accepted:
            return False

        add_qty = int(dialog.selected_quantity)
        new_qty = current_qty + add_qty
        if new_qty > available:
            QMessageBox.warning(self, 'Insufficient stock', f'Only {available} units are available for {product.description}.')
            return False

        if product.id in self.cart:
            self.cart[product.id]['quantity'] = new_qty
        else:
            self.cart[product.id] = {
                'product_id': product.id,
                'part_no': product.part_no,
                'description': product.description,
                'brand': product.brand or '',
                'vehicle_make': product.vehicle_make,
                'vehicle_model': product.vehicle_model,
                'unit_price': product.selling_price,
                'quantity': add_qty,
            }
        self.refresh_cart()
        return True

    def change_selected_quantity(self):
        row = self.cart_table.currentRow()
        if row < 0:
            QMessageBox.information(self, 'Select an item', 'Select a cart item first.')
            return
        item = self.cart_table.item(row, 0)
        product_id = item.data(Qt.UserRole) if item else None
        cart_item = self.cart.get(product_id)
        if not cart_item:
            return
        product = self.products.get_product_by_id(product_id)
        if not product:
            QMessageBox.warning(self, 'Product not found', 'The product is no longer available.')
            return
        dialog = QuantityDialog(product, int(product.quantity_on_hand), current=int(cart_item['quantity']), mode='set', parent=self)
        if dialog.exec() == QDialog.Accepted:
            cart_item['quantity'] = int(dialog.selected_quantity)
            self.refresh_cart()

    def remove_selected(self):
        row = self.cart_table.currentRow()
        if row < 0:
            QMessageBox.information(self, 'Select an item', 'Select a cart item to delete.')
            return
        item = self.cart_table.item(row, 0)
        product_id = item.data(Qt.UserRole) if item else None
        cart_item = self.cart.get(product_id)
        if not cart_item:
            return
        answer = QMessageBox.question(
            self,
            'Delete cart item',
            f'Delete {cart_item["part_no"]} - {cart_item["description"]} from the cart?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if answer == QMessageBox.Yes:
            del self.cart[product_id]
            self.refresh_cart()

    def clear_cart(self):
        if not self.cart:
            return
        answer = QMessageBox.question(
            self,
            'Clear cart',
            'Delete all items from the current cart?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if answer == QMessageBox.Yes:
            self.cart.clear()
            self.refresh_cart()

    def refresh_cart(self):
        self.cart_table.setSortingEnabled(False)
        self.cart_table.clearContents()
        self.cart_table.setRowCount(len(self.cart))
        total = 0.0
        for row_idx, item in enumerate(self.cart.values()):
            qty = int(item['quantity'])
            unit_price = float(item['unit_price'])
            line_total = qty * unit_price
            total += line_total
            vehicle = f'{item.get("vehicle_make") or ""} {item.get("vehicle_model") or ""}'.strip()
            values = [item['part_no'], item['description'], item['brand'], vehicle, str(qty), money(unit_price), money(line_total)]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if column == 0:
                    cell.setData(Qt.UserRole, item['product_id'])
                self.cart_table.setItem(row_idx, column, cell)
        self.total.setText(money(total))

    def edit_customer(self):
        d = CustomerDialog(self.sales, self, self.customer)
        if d.exec() != QDialog.Accepted:
            return
        self.customer = d.values()
        self.selected_vehicle = None
        vehicle = f"{self.customer.get('vehicle_make') or ''} {self.customer.get('vehicle_model') or ''}".strip()
        label = self.customer['name']
        if vehicle:
            label += f' - {vehicle}'
        if self.customer.get('vehicle_registration'):
            label += f' ({self.customer["vehicle_registration"]})'
        if self.customer.get('phone'):
            label += f' | {self.customer["phone"]}'
        self.customer_label.setText(label)
        vehicle_text = vehicle or 'No vehicle details captured'
        phone_text = self.customer.get('phone') or 'No phone'
        self.customer_detail.setText(f'{self.customer["name"]} | {phone_text} | {vehicle_text}' + (f' | Reg: {self.customer["vehicle_registration"]}' if self.customer.get('vehicle_registration') else ''))

    def select_customer(self):
        term, accepted = QInputDialog.getText(self, 'Find customer', 'Name, phone, email, code, or company:')
        if not accepted: return
        customers = self.crm.search_customers(term)
        if not customers:
            QMessageBox.information(self, 'No customers', 'No active customers matched that search.'); return
        labels = [f'{customer.customer_code} | {customer.name} | {customer.company or customer.phone or ""}' for customer in customers]
        selected, accepted = QInputDialog.getItem(self, 'Select customer', 'Customer', labels, 0, False)
        if not accepted: return
        customer = customers[labels.index(selected)]
        self.customer = customer.to_dict(); self.selected_vehicle = None
        self.customer_label.setText(f'{customer.customer_code} | {customer.name}')
        self.customer_detail.setText(f'{customer.name} | {customer.phone or "No phone"} | {customer.company or ""}')

    def select_vehicle(self):
        if not self.customer or not self.customer.get('id'):
            QMessageBox.information(self, 'Select customer', 'Select an existing customer before selecting a vehicle.'); return
        vehicles = self.crm.list_vehicles(self.customer['id'])
        if not vehicles:
            QMessageBox.information(self, 'No vehicles', 'This customer has no active vehicles. Create one from Customers.'); return
        labels = [f'{vehicle.registration_number} | {vehicle.make or ""} {vehicle.model or ""}'.strip() for vehicle in vehicles]
        selected, accepted = QInputDialog.getItem(self, 'Select vehicle', 'Vehicle', labels, 0, False)
        if not accepted: return
        vehicle = vehicles[labels.index(selected)]; self.selected_vehicle = vehicle.to_dict()
        self.customer['vehicle_registration'] = vehicle.registration_number; self.customer['vehicle_make'] = vehicle.make; self.customer['vehicle_model'] = vehicle.model
        self.customer_detail.setText(f"{self.customer['name']} | {vehicle.registration_number} | {(vehicle.make or '')} {(vehicle.model or '')}".strip())

    def payment(self):
        if not self.cart:
            QMessageBox.information(self, 'Cart empty', 'Add a product before taking payment.')
            return
        if self.user and not self.user.has_permission('MAKE_SALE'):
            QMessageBox.warning(self, 'Permission denied', 'Your role is not allowed to make sales.')
            return
        if not self.customer:
            self.edit_customer()
            if not self.customer:
                return
        cart_total = sum(
            float(item['quantity']) * float(item['unit_price']) *
            (1 + float(self.products.get_product_by_id(product_id).vat_rate or 0) / 100)
            for product_id, item in self.cart.items()
        )
        d = PaymentDialog(cart_total, self)
        if d.exec() != QDialog.Accepted:
            return
        try:
            customer = self.customer
            customer_id = customer.get('id') or self.sales.find_or_create_customer(
                customer['name'], customer.get('phone'), customer.get('email'),
                customer.get('vehicle_make'), customer.get('vehicle_model'), customer.get('vehicle_registration'),
                customer.get('city')
            )
            sale = self.sales.create_sale(
                customer_name=customer['name'],
                customer_phone=customer.get('phone'),
                customer_id=customer_id,
                customer_email=customer.get('email'),
                customer_city=customer.get('city'),
                vehicle_make=customer.get('vehicle_make'),
                vehicle_model=customer.get('vehicle_model'),
                vehicle_registration=customer.get('vehicle_registration'),
                user_id=self.user.id if self.user else 1,
                cashier_name=self.user.full_name if self.user else 'Administrator',
                vehicle_id=self.selected_vehicle.get('id') if self.selected_vehicle else None,
            )
            for product_id, item in self.cart.items():
                self.sales.add_item_to_sale(sale, product_id, item['quantity'], item['unit_price'])
            for payment in d.payments:
                self.sales.add_payment(sale, payment['method'], payment['amount'], payment['currency'], payment['tendered'])
            sale_id = self.sales.complete_sale(sale)
            quote_id = getattr(self, '_loaded_quote_id', None)
            if quote_id is not None:
                self.sales.mark_quotation_converted(quote_id, sale_id)
                del self._loaded_quote_id
            self.invoice_status.setText(f'Invoice: {sale.invoice_number} saved | {money(sale.total, d.currency)}')
            QMessageBox.information(self, 'Invoice created', f'Invoice {sale.invoice_number} saved successfully.\n\nCustomer: {customer["name"]}\nPhone: {customer.get("phone") or "—"}\nVehicle: {(customer.get("vehicle_make") or "")} {(customer.get("vehicle_model") or "")}\nRegistration: {customer.get("vehicle_registration") or "—"}\n\nTotal: {money(sale.total, d.currency)}\nSale ID: {sale_id}')
            self.cart.clear()
            self.refresh_cart()
            self.customer = None
            self.selected_vehicle = None
            self.customer_label.setText('Walk-in customer')
            self.customer_detail.setText('Walk-in customer | No vehicle details captured')
            self.invoice_status.setText(f'Invoice: {sale.invoice_number} saved')
            self.last_sale = sale
            self.print_receipt_btn.setEnabled(True)
            self.search('')
            self.scan.setFocus()
        except Exception as e:
            QMessageBox.critical(self, 'Payment failed', str(e))

    def hold_sale(self):
        if not self.cart:
            QMessageBox.information(self, 'Cart empty', 'Add a product before parking a sale.'); return
        try:
            held = self.sales.hold_sale(self.cart, self.customer, self.user.id if self.user else None)
            self.cart.clear(); self.customer = None; self.refresh_cart(); self.customer_label.setText('Walk-in customer'); self.customer_detail.setText('Walk-in customer | No vehicle details captured')
            QMessageBox.information(self, 'Sale parked', f"{held['hold_number']} is ready to resume.")
        except Exception as exc: QMessageBox.critical(self, 'Could not park sale', str(exc))

    def resume_held_sale(self):
        held_sales = self.sales.list_held_sales()
        if not held_sales:
            QMessageBox.information(self, 'No held sales', 'There are no parked sales to resume.'); return
        labels = [f"{held['hold_number']} | {held['created_at']}" for held in held_sales]
        label, accepted = QInputDialog.getItem(self, 'Resume held sale', 'Held sale', labels, 0, False)
        if not accepted: return
        held = self.sales.release_held_sale(held_sales[labels.index(label)]['id']); self.cart = held['cart']; self.customer = held['customer'] or None; self.refresh_cart()
        if self.customer: self.customer_label.setText(self.customer.get('name') or 'Walk-in customer'); self.customer_detail.setText(f"{self.customer.get('name') or 'Walk-in customer'} | {self.customer.get('phone') or 'No phone'}")
        QMessageBox.information(self, 'Sale resumed', f"{held['hold_number']} has been restored to the cart.")

    def print_receipt(self):
        if not getattr(self, 'last_sale', None):
            return
        sale = self.last_sale
        lines = ''.join(f"<tr><td>{item.part_no}</td><td>{item.quantity}</td><td>{money(item.line_total)}</td></tr>" for item in sale.items)
        document = QTextDocument()
        document.setHtml(f"<h1>Receipt</h1><p>{sale.invoice_number}<br>{system_clock.display_str()}<br>Cashier: {sale.cashier_name}</p><p>{sale.customer_name}<br>{sale.customer_phone or ''}<br>{sale.customer_email or ''}<br>{sale.customer_city or ''}</p><table border='1' cellspacing='0' cellpadding='5'><tr><th>Part</th><th>Qty</th><th>Total</th></tr>{lines}</table><p><b>Subtotal: {money(sale.subtotal)}<br>VAT: {money(sale.vat_amount)}<br>Total: {money(sale.total, sale.payments[0].currency if sale.payments else None)}</b></p>")
        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() == QDialog.Accepted:
            document.print_(printer)

    def create_quote(self):
        if not self.cart:
            QMessageBox.information(self, 'Cart empty', 'Add a product before creating a quotation.')
            return
        customer = self.customer or {}
        try:
            quote = self.sales.create_quotation(self.cart, customer, self.user.id if self.user else None, self.selected_vehicle.get('id') if self.selected_vehicle else None)
            quote = self.sales.change_quotation_status(quote['id'], 'ISSUED', self.user.id if self.user else None)
        except Exception as exc: QMessageBox.critical(self, 'Quotation failed', str(exc)); return
        quote_number = quote['quote_number']
        rows = []
        subtotal = 0.0
        for item in self.cart.values():
            line_total = float(item['quantity']) * float(item['unit_price'])
            subtotal += line_total
            rows.append(f"<tr><td>{item['part_no']}</td><td>{item['description']}</td><td>{item['quantity']}</td><td>{money(item['unit_price'])}</td><td>{money(line_total)}</td></tr>")
        html = f"<h1>Quotation</h1><p><b>{quote_number}</b><br>{system_clock.display_str()}</p><p><b>Customer:</b> {customer.get('name') or 'Walk-in customer'}<br>Phone: {customer.get('phone') or ''}<br>Email: {customer.get('email') or ''}<br>City: {customer.get('city') or ''}</p><table border='1' cellspacing='0' cellpadding='5'><tr><th>Part</th><th>Description</th><th>Qty</th><th>Unit price</th><th>Line total</th></tr>{''.join(rows)}</table><p><b>Subtotal: {money(subtotal)}</b><br><b>Total: {money(subtotal)}</b></p><p>Prepared by: {self.user.full_name if self.user else 'Administrator'}</p>"
        document = QTextDocument()
        document.setHtml(html)
        preview = QMessageBox(self)
        preview.setWindowTitle('Quotation preview')
        preview.setTextFormat(Qt.RichText)
        preview.setText(html)
        print_button = preview.addButton('Print Quotation', QMessageBox.AcceptRole)
        save = preview.addButton('Save PDF', QMessageBox.AcceptRole)
        preview.addButton(QMessageBox.Close)
        preview.exec()
        if preview.clickedButton() == print_button:
            printer = QPrinter(QPrinter.HighResolution)
            dialog = QPrintDialog(printer, self)
            if dialog.exec() == QDialog.Accepted:
                document.print_(printer)
            return
        if preview.clickedButton() != save:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Save quotation', f'{quote_number}.pdf', 'PDF files (*.pdf)')
        if not path:
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        document.print_(printer)

    def quotation_history(self):
        quotes = self.sales.list_quotations(include_closed=True)
        if not quotes:
            QMessageBox.information(self, 'No quotations', 'No quotation history is available.'); return
        labels = [f"{quote['quote_number']} | {quote['status']} | {money(quote['total'])}" for quote in quotes]
        label, accepted = QInputDialog.getItem(self, 'Quotation history', 'Quotation', labels, 0, False)
        if not accepted: return
        quote = quotes[labels.index(label)]
        if quote['status'] in ('DRAFT', 'ISSUED'):
            action, accepted = QInputDialog.getItem(self, 'Quotation action', 'Action', ['Reprint', 'Load for payment'], 0, False)
            if not accepted: return
            if action == 'Load for payment':
                self.cart = {item['product_id']: {key: item[key] for key in ('product_id', 'part_no', 'description', 'brand', 'vehicle_make', 'vehicle_model', 'unit_price', 'quantity')} for item in quote['items']}; self.customer = quote['customer'] or None; self._loaded_quote_id = quote['id']; self.refresh_cart()
                QMessageBox.information(self, 'Quotation loaded', 'The quotation is in the cart. Take payment to complete the sale.'); return
        rows = ''.join(f"<tr><td>{item['part_no']}</td><td>{item['description']}</td><td>{item['quantity']}</td><td>{money(item['line_total'])}</td></tr>" for item in quote['items'])
        document = QTextDocument(); document.setHtml(f"<h1>Quotation</h1><p><b>{quote['quote_number']}</b></p><p>{quote['customer'].get('name') or 'Walk-in customer'}</p><table border='1'><tr><th>Part</th><th>Description</th><th>Qty</th><th>Total</th></tr>{rows}</table><p><b>Total: {money(quote['total'])}</b></p>")
        printer = QPrinter(QPrinter.HighResolution); dialog = QPrintDialog(printer, self)
        if dialog.exec() == QDialog.Accepted: document.print_(printer)

class InventoryPage(QWidget):
    def __init__(self,products,user=None):
        super().__init__(); self.products=products; self.user=user; self.sheets=SpreadsheetService(); self._spreadsheet_thread=None; self._spreadsheet_worker=None; l=QVBoxLayout(self); l.setContentsMargins(28,24,28,24); h=QHBoxLayout(); t=QLabel('Inventory'); t.setObjectName('pageTitle'); h.addWidget(t); h.addStretch(); self.filter=QLineEdit(); self.filter.setPlaceholderText('Search products'); self.filter.setMaximumWidth(280); self.filter.textChanged.connect(self.load); h.addWidget(self.filter); a=QPushButton('Add product'); a.setObjectName('primary'); a.setIcon(icon('plus')); a.clicked.connect(self.add_product); h.addWidget(a); l.addLayout(h)
        can_edit_stock=bool(not user or user.is_admin() or user.has_permission('ADD_STOCK') or user.has_permission('ADJUST_STOCK'))
        self.delete_btn=QPushButton('Delete selected'); self.delete_btn.setIcon(icon('delete')); self.delete_btn.setEnabled(False); self.delete_btn.setToolTip('Permanently delete a product with no sales, stock, or return history'); self.delete_btn.clicked.connect(self.delete_selected); h.addWidget(self.delete_btn)
        sh=QHBoxLayout(); sh.addWidget(QLabel('Inventory spreadsheet:')); sh.addSpacing(4)
        tmpl_btn=QPushButton('Download template'); tmpl_btn.setIcon(icon('invoice')); tmpl_btn.clicked.connect(self.download_template); sh.addWidget(tmpl_btn)
        self.import_btn=QPushButton('Import spreadsheet'); self.import_btn.setIcon(icon('sync')); self.import_btn.setEnabled(can_edit_stock); self.import_btn.setToolTip('Enter stock once in Excel and bring it into the system' if can_edit_stock else 'Your role cannot import stock changes'); self.import_btn.clicked.connect(self.import_spreadsheet); sh.addWidget(self.import_btn)
        export_btn=QPushButton('Export full inventory'); export_btn.setIcon(icon('package')); export_btn.clicked.connect(self.export_spreadsheet); sh.addWidget(export_btn)
        self.undo_import_btn=QPushButton('Undo last inventory import'); self.undo_import_btn.setIcon(icon('refresh')); self.undo_import_btn.setEnabled(bool(user and user.is_admin())); self.undo_import_btn.clicked.connect(self.undo_last_import); sh.addWidget(self.undo_import_btn)
        sh.addStretch(); l.addLayout(sh)
        s=products.get_inventory_summary(); self.summary_grid=QGridLayout(); self.summary_grid.setSpacing(12); l.addLayout(self.summary_grid); self._fill_summary(s); self.table=QTableWidget(0,7); self.table.setHorizontalHeaderLabels(['Part No','Description','Brand','Vehicle','Price','Stock','Status']); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); setup_table(self.table); self.table.itemSelectionChanged.connect(lambda: self.delete_btn.setEnabled(self.table.currentRow() >= 0)); self.table.itemActivated.connect(lambda _item: self.delete_selected()); l.addWidget(self.table,1); delete_shortcut=QShortcut(QKeySequence('Delete'),self); delete_shortcut.setContext(Qt.WidgetWithChildrenShortcut); delete_shortcut.activated.connect(self.delete_selected); self.load()
    def _fill_summary(self,s):
        while self.summary_grid.count():
            item=self.summary_grid.takeAt(0); item.widget().deleteLater() if item.widget() else None
        for i,w in enumerate([card('Total products',str(s['total_products']),'Active catalog',icon_name='package'),card('Stock value',money(s['inventory_value']),'At cost',icon_name='chart'),card('Low stock',str(s['low_stock']),'Reorder soon',icon_name='warning'),card('Out of stock',str(s['out_of_stock']),'Critical',icon_name='error')]):
            self.summary_grid.addWidget(w,0,i)
    def load(self,text=None):
        text=text if isinstance(text,str) else self.filter.text()
        items=self.products.search_products(text) if text else self.products.get_all_products(); self.table.setRowCount(len(items))
        for r,p in enumerate(items):
            status='OUT OF STOCK' if p.is_out_of_stock() else 'LOW STOCK' if p.is_low_stock() else 'IN STOCK'; vals=[p.part_no,p.description,p.brand,f'{p.vehicle_make or ""} {p.vehicle_model or ""}'.strip(),money(p.selling_price,p.currency),str(p.quantity_on_hand),status]
            for c,v in enumerate(vals):
                cell=QTableWidgetItem(v)
                if c == 0: cell.setData(Qt.UserRole,p.id)
                self.table.setItem(r,c,cell)
        self._fill_summary(self.products.get_inventory_summary())
        self.delete_btn.setEnabled(self.table.currentRow() >= 0)
    def delete_selected(self):
        row=self.table.currentRow()
        if row < 0:return
        product_id=self.table.item(row,0).data(Qt.UserRole) if self.table.item(row,0) else None
        product=self.products.get_product_by_id(product_id) if product_id is not None else None
        if not product:return
        answer=QMessageBox.warning(self,'Delete inventory item',f"Permanently delete {product.part_no}? This cannot be undone. Products with history cannot be permanently deleted.",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
        if answer != QMessageBox.Yes:return
        try:
            self.products.delete_product(product.id,self.user.id if self.user else 0)
            self.load(self.filter.text())
        except Exception as exc: QMessageBox.critical(self,'Delete failed',str(exc))
    def add_product(self):
        d=ProductDialog(self)
        if d.exec()!=QDialog.Accepted:return
        try:self.products.create_product(d.value()); self.load(self.filter.text()); QMessageBox.information(self,'Saved','Product saved successfully.')
        except Exception as e:QMessageBox.critical(self,'Could not save product',str(e))
    def download_template(self):
        path,_=QFileDialog.getSaveFileName(self,'Save inventory template','inventory_template.xlsx','Excel files (*.xlsx)')
        if not path:return
        self._run_spreadsheet(path, 'template', self.sender())
    def export_spreadsheet(self):
        can_see_cost=bool(not self.user or self.user.is_admin() or self.user.has_permission('VIEW_COST_PRICE'))
        path,_=QFileDialog.getSaveFileName(self,'Export full inventory','inventory_export.xlsx','Excel files (*.xlsx)')
        if not path:return
        self._run_spreadsheet(path, 'export', self.sender(), can_see_cost)

    def _run_spreadsheet(self, path, operation, button, include_cost_price=True):
        if self._spreadsheet_thread is not None and self._spreadsheet_thread.isRunning():
            return
        self._spreadsheet_thread = QThread(self)
        self._spreadsheet_worker = SpreadsheetWorker(path, operation, include_cost_price, self.user.id if self.user else None)
        self._spreadsheet_path = path
        self._spreadsheet_operation = operation
        self._spreadsheet_button = button
        self._spreadsheet_worker.moveToThread(self._spreadsheet_thread)
        self._spreadsheet_thread.started.connect(self._spreadsheet_worker.run)
        self._spreadsheet_worker.finished.connect(self._spreadsheet_finished)
        self._spreadsheet_worker.failed.connect(self._spreadsheet_failed)
        self._spreadsheet_worker.finished.connect(self._spreadsheet_thread.quit)
        self._spreadsheet_worker.failed.connect(self._spreadsheet_thread.quit)
        self._spreadsheet_thread.finished.connect(self._spreadsheet_cleanup)
        button.setEnabled(False)
        button.setText('Importing inventory...' if operation == 'import' else 'Generating inventory spreadsheet...')
        logger.info('UI REFRESH START')
        self._spreadsheet_thread.start()

    def _spreadsheet_finished(self, result):
        path = self._spreadsheet_path
        operation = self._spreadsheet_operation
        button = self._spreadsheet_button
        refresh_started = time.perf_counter()
        logger.info('UI REFRESH START')
        self.load(self.filter.text())
        logger.info('UI REFRESH COMPLETE elapsed=%.3fs', time.perf_counter() - refresh_started)
        button.setEnabled(True)
        button.setText('Download template' if operation == 'template' else 'Import spreadsheet' if operation == 'import' else 'Export full inventory')
        if operation == 'template':
            QMessageBox.information(self,'Template ready',f'Blank inventory template saved to:\n{path}')
        elif operation == 'import':
            summary=f"{result.created} product(s) created\n{result.updated} product(s) updated\n{result.unchanged} row(s) already matched\n{len(result.errors)} row(s) had errors"
            if result.errors: summary += '\n\n' + '\n'.join(result.errors[:10])
            QMessageBox.information(self,'Import complete',summary)
        else:
            QMessageBox.information(self,'Exported',f'{result} product(s) exported to:\n{path}')

    def _spreadsheet_failed(self, error):
        button = self._spreadsheet_button
        button.setEnabled(True)
        button.setText('Import spreadsheet' if self._spreadsheet_operation == 'import' else 'Download template' if self._spreadsheet_operation == 'template' else 'Export full inventory')
        QMessageBox.critical(self,'Spreadsheet operation failed',error)

    def _spreadsheet_cleanup(self):
        if self._spreadsheet_worker:
            self._spreadsheet_worker.deleteLater()
        if self._spreadsheet_thread:
            self._spreadsheet_thread.deleteLater()
        self._spreadsheet_worker=None
        self._spreadsheet_thread=None
    def import_spreadsheet(self):
        path,_=QFileDialog.getOpenFileName(self,'Import inventory spreadsheet','','Excel files (*.xlsx)')
        if not path:return
        self._run_spreadsheet(path, 'import', self.import_btn)

    def undo_last_import(self):
        if not self.user or not self.user.is_admin():
            QMessageBox.warning(self,'Permission denied','Only an administrator can undo an inventory import.')
            return
        imports=self.sheets.list_imports(1)
        if not imports:
            QMessageBox.information(self,'No imports','There are no tracked inventory imports to undo.')
            return
        batch=imports[0]
        if batch['status'] == 'UNDONE':
            QMessageBox.information(self,'Already undone','The latest inventory import has already been undone.')
            return
        answer=QMessageBox.warning(self,'Undo inventory import',f"Undo {batch['filename']}?\n\nRows: {batch['total_rows']}\nNew products: {batch['created_count']}\nUpdated products: {batch['updated_count']}\n\nThis reverses only this import. Historical products and transactions will be preserved.",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
        if answer != QMessageBox.Yes:return
        try:
            result=self.sheets.undo_import(batch['id'],self.user.id)
            self.load(self.filter.text())
            QMessageBox.information(self,'Import undone',f"Removed: {result['removed']}\nRestored: {result['restored']}")
        except Exception as exc: QMessageBox.critical(self,'Could not undo import',str(exc))

class ProductDialog(QDialog):
    def __init__(self, parent=None, product=None):
        super().__init__(parent); self.product=product; self.setWindowTitle('Edit Product' if product else 'Add Product'); self.setMinimumWidth(430); self.setStyleSheet(STYLESHEET)
        l=QVBoxLayout(self); form=QFormLayout(); self.fields={}
        specs=[('part_no','Part number'),('description','Product name / description'),('brand','Brand'),('barcode','Barcode'),('oem_number','OEM number'),('vehicle_make','Vehicle make'),('vehicle_model','Vehicle model'),('vehicle_year_from','Vehicle year from'),('vehicle_year_to','Vehicle year to'),('cost_price','Cost price'),('selling_price','Selling price'),('quantity_on_hand','Initial stock'),('reorder_level','Reorder level')]
        for key,label in specs:
            w=QLineEdit(); w.setPlaceholderText(label); self.fields[key]=w; form.addRow(label,w)
        if product:
            for key,w in self.fields.items(): w.setText(str(getattr(product,key,'')))
        l.addLayout(form); self.error=QLabel(''); self.error.setStyleSheet(f'color:{COLORS["danger"]};'); self.error.setWordWrap(True); l.addWidget(self.error); buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); l.addWidget(buttons)
    def value(self):
        def num(k, cast=float):
            try:return cast(self.fields[k].text() or 0)
            except ValueError: raise ValueError(f"{k.replace('_',' ').title()} must be a number")
        return Product(id=self.product.id if self.product else None, barcode=self.fields['barcode'].text().strip() or None, part_no=self.fields['part_no'].text().strip(), oem_number=self.fields['oem_number'].text().strip() or None, description=self.fields['description'].text().strip(), brand=self.fields['brand'].text().strip(), vehicle_make=self.fields['vehicle_make'].text().strip() or None, vehicle_model=self.fields['vehicle_model'].text().strip() or None, vehicle_year_from=num('vehicle_year_from',int) if self.fields['vehicle_year_from'].text().strip() else None, vehicle_year_to=num('vehicle_year_to',int) if self.fields['vehicle_year_to'].text().strip() else None, cost_price=num('cost_price'), selling_price=num('selling_price'), quantity_on_hand=num('quantity_on_hand',int), reorder_level=num('reorder_level',int))
    def accept(self):
        try:
            product=self.value()
            if not product.part_no or not product.description:
                raise ValueError('Part number and product name are required.')
            if product.vehicle_year_from is not None and product.vehicle_year_to is not None and product.vehicle_year_from > product.vehicle_year_to:
                raise ValueError('Vehicle year from must not be later than vehicle year to.')
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        super().accept()

class ProductsPage(QWidget):
    def __init__(self, products, user):
        super().__init__(); self.products=products; self.user=user; l=QVBoxLayout(self); l.setContentsMargins(28,24,28,24); h=QHBoxLayout(); t=QLabel('Products'); t.setObjectName('pageTitle'); h.addWidget(t); h.addStretch(); self.search_box=QLineEdit(); self.search_box.setPlaceholderText('Search products'); self.search_box.textChanged.connect(self.load); h.addWidget(self.search_box); self.show_archived=QCheckBox('Show archived'); self.show_archived.toggled.connect(lambda _checked: self.load(self.search_box.text())); h.addWidget(self.show_archived); add=QPushButton('Add product'); add.setObjectName('primary'); add.setIcon(icon('plus')); add.setEnabled(bool(not user or user.has_permission('CREATE_PRODUCT'))); add.clicked.connect(self.add); h.addWidget(add); self.archive=QPushButton('Archive selected'); self.archive.setIcon(icon('archive')); self.archive.clicked.connect(self.archive_selected); h.addWidget(self.archive); self.delete_btn=QPushButton('Permanently delete'); self.delete_btn.setIcon(icon('delete')); self.delete_btn.setToolTip('Permanently delete only products without sale, stock, or return history'); self.delete_btn.clicked.connect(self.delete_selected); h.addWidget(self.delete_btn); self.archive_all=QPushButton('Clear active catalog'); self.archive_all.setIcon(icon('archive')); self.archive_all.setToolTip('Deletes unreferenced products and archives products with history'); self.archive_all.clicked.connect(self.archive_all_active); h.addWidget(self.archive_all); self.restore=QPushButton('Restore selected'); self.restore.setIcon(icon('refresh')); self.restore.clicked.connect(self.restore_selected); h.addWidget(self.restore); l.addLayout(h); self.table=QTableWidget(0,8); self.table.setHorizontalHeaderLabels(['Part No','Description','Brand','Vehicle','Price','Stock','Status','Edit']); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); setup_table(self.table); self.table.itemSelectionChanged.connect(self._update_action_buttons); self.table.cellDoubleClicked.connect(lambda row,_: self.save_product(self.items[row])); l.addWidget(self.table,1); delete_shortcut=QShortcut(QKeySequence('Delete'),self); delete_shortcut.setContext(Qt.WidgetWithChildrenShortcut); delete_shortcut.activated.connect(self.delete_selected); self.load()
    def load(self,text=None):
        text=text if isinstance(text,str) else self.search_box.text()
        all_items=self.products.get_all_products(active_only=False) if self.show_archived.isChecked() else self.products.get_all_products()
        term=text.strip().lower(); self.items=[p for p in all_items if not term or term in ' '.join(str(x or '') for x in (p.part_no,p.description,p.brand,p.barcode,p.vehicle_make,p.vehicle_model)).lower()]; self.table.setRowCount(len(self.items))
        for r,p in enumerate(self.items):
            status='ARCHIVED' if not p.active else 'OUT OF STOCK' if p.is_out_of_stock() else 'LOW STOCK' if p.is_low_stock() else 'IN STOCK'; vals=[p.part_no,p.description,p.brand,f'{p.vehicle_make or ""} {p.vehicle_model or ""}'.strip(),money(p.selling_price,p.currency),str(p.quantity_on_hand),status,'Double-click to edit']
            for c,v in enumerate(vals):self.table.setItem(r,c,QTableWidgetItem(v))
        selected=self._selected() if hasattr(self,'_selected') else None
        self.archive.setEnabled(bool(selected and selected.active))
        self.restore.setEnabled(bool(selected and not selected.active and self.show_archived.isChecked()))
    def _update_action_buttons(self):
        p=self._selected()
        self.archive.setEnabled(bool(p and p.active))
        self.restore.setEnabled(bool(p and not p.active and self.show_archived.isChecked()))

    def add(self): self.save_product(None)
    def save_product(self,existing):
        d=ProductDialog(self,existing)
        if d.exec()!=QDialog.Accepted:return
        try:
            p=d.value()
            if not p.part_no or not p.description:raise ValueError('Part number and description are required')
            if existing and self.user and not self.user.has_permission('EDIT_PRODUCT'): raise PermissionError('Your role is not allowed to edit products')
            if existing:self.products.update_product(p)
            else:self.products.create_product(p)
            self.load(self.search_box.text()); QMessageBox.information(self,'Saved','Product saved successfully.')
        except Exception as e: QMessageBox.critical(self,'Could not save product',str(e))
    def _selected(self):
        row=self.table.currentRow(); return self.items[row] if 0<=row<len(self.items) else None
    def archive_selected(self): self._change_state(False)
    def delete_selected(self):
        p=self._selected()
        if not p:return
        permission='DELETE_PRODUCT'; action='Permanently delete product'; approver=None
        try:
            if not self.user or not self.user.has_permission(permission) or not self.user.is_admin():
                dlg=AuthorizationDialog(action,self.user.id if self.user else 0,permission,self)
                if dlg.exec()!=QDialog.Accepted:return
                approver=dlg.approver.id; reason=''
            else:
                reason=''
            answer=QMessageBox.warning(self,'Confirm permanent deletion',f'Permanently delete {p.part_no}? This cannot be undone.',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
            if answer != QMessageBox.Yes:return
            self.products.delete_product(p.id,self.user.id if self.user else 0,approver,reason)
            self.load(self.search_box.text())
        except Exception as e: QMessageBox.critical(self,'Permanent deletion failed',str(e))
    def restore_selected(self): self._change_state(True)
    def archive_all_active(self):
        if not self.user or not self.user.is_admin() or not self.user.has_permission('DELETE_PRODUCT'):
            QMessageBox.warning(self, 'Permission denied', 'Only an authorized administrator can archive all products.')
            return
        answer=QMessageBox.warning(self,'Clear active catalog','Products with no history will be permanently deleted. Products linked to sales, stock, returns, quotations, or imports will be archived to preserve history. The active catalog will be empty. Continue?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
        if answer != QMessageBox.Yes:return
        confirm,ok=QInputDialog.getText(self,'Confirm catalog clear','Type CLEAR CATALOG to continue:')
        if not ok or confirm.strip().upper() != 'CLEAR CATALOG':return
        if getattr(self, '_bulk_archive_thread', None) and self._bulk_archive_thread.isRunning(): return
        self._bulk_archive_thread = QThread(self); self._bulk_archive_worker = CatalogClearWorker(self.user.id)
        self._bulk_archive_worker.moveToThread(self._bulk_archive_thread)
        self._bulk_archive_thread.started.connect(self._bulk_archive_worker.run)
        self._bulk_archive_worker.progress.connect(self._bulk_archive_progress)
        self._bulk_archive_worker.finished.connect(self._bulk_archive_finished)
        self._bulk_archive_worker.failed.connect(self._bulk_archive_failed)
        self._bulk_archive_worker.finished.connect(self._bulk_archive_thread.quit); self._bulk_archive_worker.failed.connect(self._bulk_archive_thread.quit)
        self._bulk_archive_thread.finished.connect(self._bulk_archive_cleanup)
        self.archive_all.setEnabled(False); self.archive_all.setText('Preparing...'); self._bulk_archive_thread.start()

    def _bulk_archive_progress(self, status): self.archive_all.setText(status)
    def _bulk_archive_finished(self, result):
        self.show_archived.setChecked(False); self.load(self.search_box.text()); self.archive_all.setEnabled(True); self.archive_all.setText('Clear active catalog'); QMessageBox.information(self, 'Catalog cleared', f"Deleted: {result['deleted']}\nArchived to preserve history: {result['archived']}")
    def _bulk_archive_failed(self, error):
        self.archive_all.setEnabled(True); self.archive_all.setText('Clear active catalog'); QMessageBox.critical(self, 'Catalog clear failed', error)
    def _bulk_archive_cleanup(self):
        self._bulk_archive_worker.deleteLater(); self._bulk_archive_thread.deleteLater(); self._bulk_archive_worker=None; self._bulk_archive_thread=None
    def _change_state(self,restore):
        p=self._selected()
        if not p:return
        permission='RESTORE_PRODUCT' if restore else 'DELETE_PRODUCT'; action='Restore product' if restore else 'Archive product'; approver=None
        try:
            if not self.user or not self.user.has_permission(permission) or not self.user.is_admin():
                dlg=AuthorizationDialog(action,self.user.id if self.user else 0,permission,self)
                if dlg.exec()!=QDialog.Accepted:return
                approver=dlg.approver.id; reason=''
            else:
                reason=''
            if restore:
                self.products.restore_product(p.id,self.user.id if self.user else 0,approver,reason)
            else:
                self.products.archive_product(p.id,self.user.id if self.user else 0,approver,reason)
                # Keep the archived item visible immediately so the admin can verify it.
                self.show_archived.setChecked(True)
            self.load(self.search_box.text()); QMessageBox.information(self,'Completed',f'{action} completed successfully.')
        except Exception as e: QMessageBox.critical(self,f'{action} failed',str(e))

class InvoicesPage(QWidget):
    def __init__(self, user=None):
        super().__init__(); self.user=user; self.sales=SalesService(); l=QVBoxLayout(self); l.setContentsMargins(28,24,28,24); h=QHBoxLayout(); t=QLabel('Invoices'); t.setObjectName('pageTitle'); h.addWidget(t); h.addStretch(); self.search_box=QLineEdit(); self.search_box.setPlaceholderText('Search invoice or customer'); self.search_box.returnPressed.connect(self.load); h.addWidget(self.search_box); b=QPushButton('Search'); b.setIcon(icon('search')); b.clicked.connect(self.load); h.addWidget(b); self.void_btn=QPushButton('Void invoice'); self.void_btn.setIcon(icon('delete')); self.void_btn.setEnabled(bool(user and user.is_admin())); self.void_btn.clicked.connect(self.void_selected); h.addWidget(self.void_btn); self.delete_draft_btn=QPushButton('Delete draft'); self.delete_draft_btn.setIcon(icon('delete')); self.delete_draft_btn.setEnabled(bool(user and user.has_permission('invoices.view'))); self.delete_draft_btn.clicked.connect(self.delete_selected_draft); h.addWidget(self.delete_draft_btn); l.addLayout(h); self.table=QTableWidget(0,5); self.table.setHorizontalHeaderLabels(['Invoice','Customer','Subtotal','Total','Status']); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); setup_table(self.table); self.table.cellDoubleClicked.connect(self.preview); l.addWidget(self.table,1); self.load()
    def load(self):
        rows=self.sales.search_sales(self.search_box.text()) if self.search_box.text().strip() else self.sales.get_recent_sales(); self.rows=rows; self.table.setRowCount(len(rows))
        for r,s in enumerate(rows):
            for c,v in enumerate([s.invoice_number,s.customer_name,money(s.subtotal),money(s.total),s.status]):self.table.setItem(r,c,QTableWidgetItem(v))
    def preview(self,r,c):
        s=self.rows[r]; customer_lines='\n'.join(value for value in (s.customer_name, s.customer_phone, s.customer_email, s.customer_city) if value); QMessageBox.information(self,'Invoice',f'{s.invoice_number}\n{customer_lines}\nTotal: {money(s.total)}\n\nInvoice preview is ready for printing through the printer service.')
    def _selected_invoice(self):
        row=self.table.currentRow(); return self.rows[row] if 0 <= row < len(self.rows) else None
    def void_selected(self):
        sale=self._selected_invoice()
        if not sale:return
        if not self.user or not self.user.is_admin(): QMessageBox.warning(self,'Permission denied','Only an administrator can void invoices.'); return
        answer=QMessageBox.warning(self,'Void invoice',f'Void {sale.invoice_number}? The invoice and payment history will be kept and stock will be restored.',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
        if answer != QMessageBox.Yes:return
        try:self.sales.void_invoice(sale.invoice_number,self.user.id); self.load(); QMessageBox.information(self,'Invoice voided',f'{sale.invoice_number} was voided and retained in history.')
        except Exception as exc: QMessageBox.critical(self,'Could not void invoice',str(exc))
    def delete_selected_draft(self):
        sale=self._selected_invoice()
        if not sale:return
        answer=QMessageBox.warning(self,'Delete draft invoice',f'Delete draft {sale.invoice_number}? Completed invoices cannot be deleted.',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
        if answer != QMessageBox.Yes:return
        try:self.sales.delete_draft_invoice(sale.invoice_number,self.user.id); self.load(); QMessageBox.information(self,'Draft deleted',f'{sale.invoice_number} was deleted.')
        except Exception as exc: QMessageBox.critical(self,'Could not delete invoice',str(exc))

class ReturnsPage(QWidget):
    def __init__(self,user):
        super().__init__(); self.user=user; self.returns=ReturnsService(); l=QVBoxLayout(self); l.setContentsMargins(28,24,28,24); t=QLabel('Returns & Refunds'); t.setObjectName('pageTitle'); l.addWidget(t); h=QHBoxLayout(); self.invoice=QLineEdit(); self.invoice.setPlaceholderText('Search original invoice'); h.addWidget(self.invoice); find=QPushButton('Find invoice'); find.setObjectName('primary'); find.setIcon(icon('search')); find.clicked.connect(self.find); h.addWidget(find); l.addLayout(h); self.info=QLabel('Enter an invoice number to begin a return.'); self.info.setObjectName('muted'); l.addWidget(self.info); self.item_selector=QComboBox(); l.addWidget(self.item_selector); self.return_quantity=QSpinBox(); self.return_quantity.setMinimum(1); self.return_quantity.setEnabled(False); l.addWidget(self.return_quantity); self.reason=QLineEdit(); self.reason.setPlaceholderText('Return reason'); l.addWidget(self.reason); self.process=QPushButton('Create return and refund'); self.process.setObjectName('primary'); self.process.setEnabled(False); self.process.clicked.connect(self.create); l.addWidget(self.process); l.addStretch()
    def find(self):
        matches=self.returns.search_original_invoices(self.invoice.text().strip())
        if len(matches) > 1:
            labels=[f"{row['invoice_number']} | {row['customer_name'] or ''} | {row['vehicle_registration'] or ''} | {money(row['total'])}" for row in matches]
            selected,accepted=QInputDialog.getItem(self,'Search Original Invoice','Invoice',labels,0,False)
            if not accepted:return
            self.invoice.setText(matches[labels.index(selected)]['invoice_number'])
        elif len(matches) == 1:
            self.invoice.setText(matches[0]['invoice_number'])
        self.sale=self.returns.find_original_sale(self.invoice.text().strip())
        if not self.sale:self.info.setText('Invoice not found.'); self.process.setEnabled(False); return
        self.item_selector.clear()
        for item in self.sale.items:
            self.item_selector.addItem(f'{item.part_no} - {item.product_name} (sold {item.quantity})', item.id)
        self.item_selector.currentIndexChanged.connect(self._update_return_quantity)
        self.info.setText(f'Invoice {self.sale.invoice_number} - {len(self.sale.items)} item(s) - Total {money(self.sale.total)}'); self.process.setEnabled(bool(self.sale.items)); self._update_return_quantity()
    def _update_return_quantity(self):
        if not getattr(self, 'sale', None) or self.item_selector.currentIndex() < 0:
            return
        item = self.sale.items[self.item_selector.currentIndex()]
        remaining = self.returns.calculate_returnable_quantity(item.product_id, item.quantity, self.sale.id)
        self.return_quantity.setMaximum(max(1, remaining)); self.return_quantity.setEnabled(remaining > 0); self.process.setEnabled(remaining > 0)
    def create(self):
        try:
            item=self.sale.items[self.item_selector.currentIndex()]; obj=self.returns.create_return(self.sale.invoice_number,[{'product_id':item.product_id,'quantity':self.return_quantity.value(),'condition':'GOOD','return_reason':self.reason.text() or 'Customer return'}],self.reason.text() or 'Customer return',self.user.id); rid=self.returns.save_return(obj); self.returns.approve_return(rid,self.user.id); self.returns.process_return(rid,self.user.id); self.returns.process_refund(rid,'CASH_USD',self.user.id); QMessageBox.information(self,'Return complete',f'Return {obj.return_number} was processed.'); self.process.setEnabled(False)
        except Exception as e: QMessageBox.critical(self,'Return failed',str(e))

class SyncPage(QWidget):
    def __init__(self, user=None):
        super().__init__()
        self.user = user
        self.sync = SyncService()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28,22,28,28)
        layout.setSpacing(14)
        head = QHBoxLayout()
        title = QLabel('Sync Center')
        title.setObjectName('pageTitle')
        head.addWidget(title)
        head.addStretch()
        self.connection = QLabel(self.sync.connection_status())
        self.connection.setObjectName('statusOnline')
        head.addWidget(self.connection)
        layout.addLayout(head)
        sub = QLabel('Sales, stock changes and product updates are saved locally first and synchronized when the server is reachable.')
        sub.setObjectName('muted')
        layout.addWidget(sub)
        self.kpis = QGridLayout()
        self.kpis.setSpacing(10)
        layout.addLayout(self.kpis)
        actions = QHBoxLayout()
        self.now_btn = QPushButton('Sync now')
        self.now_btn.setObjectName('primary')
        self.now_btn.setIcon(icon('sync'))
        self.now_btn.clicked.connect(self.sync_now)
        self.retry_btn = QPushButton('Retry failed')
        self.retry_btn.setIcon(icon('refresh'))
        self.retry_btn.clicked.connect(self.retry)
        actions.addWidget(self.now_btn)
        actions.addWidget(self.retry_btn)
        actions.addStretch()
        layout.addLayout(actions)
        activity_panel, activity_layout = panel('Synchronization activity', 'Latest local queue records')
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['Entity','Record','Operation','Status','Updated','External ID','Error'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        setup_table(self.table)
        activity_layout.addWidget(self.table)
        layout.addWidget(activity_panel, 1)
        self.load()

    def _authorized(self):
        return bool(self.user and (self.user.is_admin() or self.user.has_permission('SYNC_DATA')))

    def load(self):
        status = self.sync.get_sync_status()
        last_rows = self.sync.db.execute_query("SELECT MAX(synced_at) last_sync FROM sync_queue WHERE status='SYNCED'")
        last = last_rows[0]['last_sync'] if last_rows else None
        state = self.sync.connection_status()
        self.connection.setText(state)
        self.connection.setObjectName('statusOnline' if state == 'ONLINE' else 'statusWarning' if state == 'OFFLINE' else 'muted')
        self.connection.style().unpolish(self.connection)
        self.connection.style().polish(self.connection)
        while self.kpis.count():
            item = self.kpis.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        values = [
            ('Pending', status.get('PENDING', 0), 'Waiting to upload', 'sync'),
            ('Syncing', status.get('SYNCING', 0), 'In progress', 'refresh'),
            ('Synced', status.get('SYNCED', 0), 'Completed', 'success'),
            ('Failed', status.get('FAILED', 0), 'Needs retry', 'error'),
        ]
        for i, (a,b,c,ic) in enumerate(values):
            self.kpis.addWidget(card(a, str(b), c, icon_name=ic), 0, i)
        rows = self.sync.db.execute_query("SELECT entity_type,entity_id,operation,status,COALESCE(synced_at,last_attempt,created_at) updated_at,external_id,error_message FROM sync_queue ORDER BY created_at DESC LIMIT 50")
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            vals = [row['entity_type'], str(row['entity_id']), row['operation'], row['status'], str(row['updated_at'] or ''), row['external_id'] or '', row['error_message'] or '']
            for c, value in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(str(value)))
        self.now_btn.setEnabled(self._authorized())
        self.retry_btn.setEnabled(self._authorized())

    def sync_now(self):
        if not self._authorized():
            QMessageBox.warning(self, 'Permission denied', 'You do not have permission to synchronize data.')
            return
        result = self.sync.sync_now()
        self.load()
        if result['status'] == 'OFFLINE':
            QMessageBox.warning(self, 'Synchronization unavailable', result['message'])
        elif result['status'] == 'NOT_CONFIGURED':
            QMessageBox.warning(self, 'Synchronization not configured', result['message'])
        else:
            QMessageBox.information(
                self,
                'Synchronization result',
                f"Uploaded: {result['uploaded']}\nDownloaded: {result['downloaded']}\nFailed: {result['failed']}\nRemaining: {result['pending']}"
            )

    def retry(self):
        if not self._authorized():
            QMessageBox.warning(self, 'Permission denied', 'You do not have permission to retry synchronization.')
            return
        self.sync.retry_failed()
        self.load()

class ReportsPage(QWidget):
    def __init__(self, user=None):
        super().__init__(); self.user=user; self.sales=SalesService(); l=QVBoxLayout(self); l.setContentsMargins(28,24,28,24); t=QLabel('Reports & Analytics'); t.setObjectName('pageTitle'); l.addWidget(t); h=QHBoxLayout(); self.filter=QLineEdit(); self.filter.setPlaceholderText('Filter by invoice, customer, vehicle'); h.addWidget(self.filter); b=QPushButton('Run sales report'); b.setObjectName('primary'); b.setIcon(icon('chart')); b.clicked.connect(self.run); h.addWidget(b); self.tax_btn=QPushButton('Tax & ZIMRA Reports'); self.tax_btn.setIcon(icon('invoice')); self.tax_btn.setEnabled(bool(user and user.is_admin())); self.tax_btn.clicked.connect(self.tax_report); h.addWidget(self.tax_btn); l.addLayout(h); self.tax_period=QComboBox(); self.tax_period.addItems(['Today','This Week','This Month','This Year','Custom Range']); self.tax_start=QDateEdit(QDate.currentDate()); self.tax_end=QDateEdit(QDate.currentDate()); self.tax_start.setCalendarPopup(True); self.tax_end.setCalendarPopup(True); self.tax_start.setVisible(False); self.tax_end.setVisible(False); self.tax_period.currentIndexChanged.connect(self._tax_dates_changed); dates=QHBoxLayout(); dates.addWidget(QLabel('Tax period')); dates.addWidget(self.tax_period); dates.addWidget(self.tax_start); dates.addWidget(self.tax_end); self.tax_print=QPushButton('Print tax report'); self.tax_print.setIcon(icon('print')); self.tax_print.setEnabled(False); self.tax_print.clicked.connect(self.print_tax); dates.addWidget(self.tax_print); self.tax_pdf=QPushButton('Save PDF'); self.tax_pdf.setIcon(icon('save')); self.tax_pdf.setEnabled(False); self.tax_pdf.clicked.connect(self.save_tax_pdf); dates.addWidget(self.tax_pdf); self.tax_csv=QPushButton('Export CSV'); self.tax_csv.setIcon(icon('invoice')); self.tax_csv.setEnabled(False); self.tax_csv.clicked.connect(self.export_tax_csv); dates.addWidget(self.tax_csv); self.tax_xlsx=QPushButton('Export Excel'); self.tax_xlsx.setIcon(icon('invoice')); self.tax_xlsx.setEnabled(False); self.tax_xlsx.clicked.connect(self.export_tax_xlsx); dates.addWidget(self.tax_xlsx); dates.addStretch(); l.addLayout(dates); self.output=QTextEdit(); self.output.setReadOnly(True); l.addWidget(self.output,1); self.run()
    def run(self):
        rows=self.sales.search_sales(self.filter.text()) if self.filter.text().strip() else self.sales.get_recent_sales(100); revenue=sum(s.total for s in rows); analytics=AnalyticsService(); daily=analytics.get_daily_sales_report(); top=analytics.get_top_products('year',10); stock=analytics.get_stock_report(); customers=analytics.get_customer_sales(); returns=analytics.get_returns_report(); lines=[f'Sales report\n\nTransactions: {len(rows)}\nRevenue: {money(revenue)}\n\nRecent sales\n' + '\n'.join(f'{s.invoice_number}  {s.customer_name}  {money(s.total)}' for s in rows), 'Daily sales\n' + '\n'.join(f"{x['day']}  sales={x['sales']}  gross={money(x['gross_sales'])}  returns={money(x['returns'])}  net={money(x['net_sales'])}  profit={money(x['profit'])}" for x in daily) or 'No sales in the selected period.', 'Top selling parts\n' + '\n'.join(f"{x['part_no']}  qty={x['quantity_sold']}  revenue={money(x['revenue'])}  profit={money(x['profit'])}" for x in top) or 'No product sales.', 'Stock report\n' + '\n'.join(f"{x['part_no']}  {x['description']}  stock={x['current_stock']}  value={money(x['stock_value'])}  {x['stock_status']}" for x in stock), 'Customer sales\n' + '\n'.join(f"{x['customer']}  purchases={x['purchases']}  spent={money(x['total_spent'])}" for x in customers), 'Returns report\n' + '\n'.join(f"{x['return_number']}  {x['invoice'] or ''}  {x['product']}  qty={x['quantity']}  refund={money(x['refund'])}  {x['reason'] or ''}" for x in returns)]; self.output.setPlainText('\n\n'.join(lines))
    def tax_report(self):
        if not self.user or not self.user.is_admin(): QMessageBox.warning(self,'Permission denied','Only an administrator can view tax reports.'); return
        from services.tax_report_service import TaxReportService
        start,end=self._tax_dates(); report=TaxReportService().summary(start,end); sales=report['sales']; self.tax_text=f"Tax & ZIMRA Report ({start} to {end}; database summary, not FDMS fiscalised)\n\nInvoices: {sales['invoices']}\nGross sales: {money(sales['gross_sales'])}\nTaxable sales: {money(sales['taxable_sales'])}\nOutput VAT: {money(sales['output_vat'])}\nDiscounts: {money(sales['discounts'])}\nReturns / credit notes: {money(report['returns'])}\nNet sales: {money(report['net_sales'])}\nZero-rated sales: {money(report['zero_rated_sales'])}\nExempt sales: {money(report['exempt_sales'])}\n\nPayment methods\n"+'\n'.join(f"{row['method']}: {money(row['amount'])}" for row in report['payments'])+'\n\nInvoice register\n'+'\n'.join(f"{row['invoice_number']}  {row['created_at']}  {row['customer_name'] or ''}  VAT {money(row['vat_amount'])}  Total {money(row['total'])}" for row in report['invoice_register']); self.tax_rows=report['invoice_register']; self.output.setPlainText(self.tax_text); self.tax_print.setEnabled(True); self.tax_pdf.setEnabled(True); self.tax_csv.setEnabled(True); self.tax_xlsx.setEnabled(True)
    def _tax_dates_changed(self):
        custom=self.tax_period.currentText() == 'Custom Range'; self.tax_start.setVisible(custom); self.tax_end.setVisible(custom)
    def _tax_dates(self):
        from datetime import date,timedelta
        today=date.today(); period=self.tax_period.currentText()
        if period == 'Today': start=today
        elif period == 'This Week': start=today-timedelta(days=today.weekday())
        elif period == 'This Month': start=today.replace(day=1)
        elif period == 'This Year': start=today.replace(month=1,day=1)
        else: return self.tax_start.date().toString('yyyy-MM-dd'),self.tax_end.date().toString('yyyy-MM-dd')
        return start.isoformat(),today.isoformat()
    def _tax_document(self):
        document=QTextDocument(); document.setPlainText(getattr(self,'tax_text','')); return document
    def print_tax(self):
        printer=QPrinter(QPrinter.HighResolution); dialog=QPrintDialog(printer,self)
        if dialog.exec()==QDialog.Accepted:self._tax_document().print_(printer)
    def save_tax_pdf(self):
        path,_=QFileDialog.getSaveFileName(self,'Save tax report','tax_zimra_report.pdf','PDF files (*.pdf)')
        if path: printer=QPrinter(QPrinter.HighResolution); printer.setOutputFormat(QPrinter.PdfFormat); printer.setOutputFileName(path); self._tax_document().print_(printer); AuditService().log_action('TAX_REPORT_PDF_EXPORTED','REPORT',None,self.user.id)
    def export_tax_csv(self):
        path,_=QFileDialog.getSaveFileName(self,'Export invoice register','tax_invoice_register.csv','CSV files (*.csv)')
        if path:
            import csv
            with open(path,'w',newline='',encoding='utf-8') as output: writer=csv.DictWriter(output,fieldnames=['invoice_number','created_at','customer_name','customer_phone','vehicle_registration','subtotal','vat_amount','total','status']); writer.writeheader(); writer.writerows(getattr(self,'tax_rows',[]))
            AuditService().log_action('TAX_REPORT_CSV_EXPORTED','REPORT',None,self.user.id)
    def export_tax_xlsx(self):
        path,_=QFileDialog.getSaveFileName(self,'Export tax report','tax_zimra_report.xlsx','Excel files (*.xlsx)')
        if path:
            from services.tax_report_service import TaxReportService
            start,end=self._tax_dates(); TaxReportService().export_xlsx(path,start,end)
            AuditService().log_action('TAX_REPORT_XLSX_EXPORTED','REPORT',None,self.user.id)

class UserCreateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.auth = AuthenticationService()
        self.setWindowTitle('Add user')
        self.setMinimumWidth(480)
        self.setStyleSheet(STYLESHEET)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.full_name = QLineEdit()
        self.full_name.setPlaceholderText('Employee full name')
        form.addRow('Full name', self.full_name)
        self.username = QLineEdit()
        self.username.setPlaceholderText('Login username')
        form.addRow('Username', self.username)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText('Temporary password')
        form.addRow('Password', self.password)
        self.error = QLabel('')
        self.error.setStyleSheet(f'color:{COLORS["danger"]};')
        self.error.setWordWrap(True)
        self.email = QLineEdit()
        self.email.setPlaceholderText('Optional email')
        form.addRow('Email', self.email)
        self.phone = QLineEdit()
        self.phone.setPlaceholderText('Optional phone')
        form.addRow('Phone', self.phone)
        self.role = QComboBox()
        rows = get_database_manager().execute_query('SELECT id,name FROM roles ORDER BY id')
        for row in rows:
            self.role.addItem(row['name'], row['id'])
        form.addRow('Role', self.role)
        layout.addLayout(form)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        full_name = self.full_name.text().strip()
        username = self.username.text().strip()
        password = self.password.text()
        if not full_name:
            raise ValueError('Full name is required.')
        if not username:
            raise ValueError('Username is required.')
        if len(password) < 6:
            raise ValueError('Password must contain at least 6 characters.')
        return {
            'full_name': full_name,
            'username': username,
            'password': password,
            'email': self.email.text().strip() or None,
            'phone': self.phone.text().strip() or None,
            'role_id': int(self.role.currentData()),
        }

    def accept(self):
        try:
            values = self.values()
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', values['username']):
                raise ValueError('Username may contain only letters, numbers, dots, underscores, and hyphens.')
            if self.auth.get_user_by_username(values['username']):
                raise ValueError('Username already exists.')
        except ValueError as exc:
            self.error.setText(str(exc))
            self.password.setFocus()
            return
        super().accept()


class UserPrivilegesDialog(QDialog):
    """Per-user privilege editor. Only an ADMIN with MANAGE_PERMISSIONS may open it."""
    def __init__(self, admin_user, target_user, parent=None):
        super().__init__(parent)
        self.admin_user = admin_user
        self.target_user = target_user
        self.auth = AuthenticationService()
        self.permissions_service = PermissionService()
        self.checks = {}
        self.loading = True
        self.setWindowTitle(f'Privileges - {target_user.full_name}')
        self.setMinimumWidth(620)
        self.setMinimumHeight(520)
        self.setStyleSheet(STYLESHEET)
        layout = QVBoxLayout(self)
        title = QLabel(f'Privileges for {target_user.full_name}')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        role = target_user.role.name if target_user.role else 'Unassigned'
        info = QLabel(f'Role: {role}  |  Select the direct privileges this user should have.')
        info.setObjectName('muted')
        layout.addWidget(info)
        if role != 'ADMIN':
            note = QLabel('Product archive/restore remain ADMIN-only for security.')
            note.setObjectName('muted')
            layout.addWidget(note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setStyleSheet(f"background:{COLORS['canvas']};")
        body_layout = QVBoxLayout(body)
        body_layout.setSpacing(10)
        enabled = {p.code for p in self.auth.get_user_permissions(target_user.id)}
        permissions = self.permissions_service.get_all_permissions()
        groups = {}
        for perm in permissions:
            groups.setdefault(perm.category or 'OTHER', []).append(perm)
        for category, items in groups.items():
            frame, frame_layout = panel(category.title(), f'{len(items)} permissions')
            grid = QGridLayout()
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(8)
            for index, perm in enumerate(items):
                box = QCheckBox(perm.code.replace('_', ' ').title())
                box.setToolTip(perm.description or '')
                box.setProperty('permission_code', perm.code)
                box.setChecked(perm.code in enabled)
                if role != 'ADMIN' and perm.code in ('DELETE_PRODUCT', 'RESTORE_PRODUCT'):
                    box.setChecked(False)
                    box.setEnabled(False)
                self.checks[perm.code] = box
                grid.addWidget(box, index // 2, index % 2)
            frame_layout.addLayout(grid)
            body_layout.addWidget(frame)
        body_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.loading = False

    def save(self):
        selected = [code for code, box in self.checks.items() if box.isChecked()]
        try:
            result = self.auth.set_user_permissions(
                self.admin_user.id,
                self.target_user.id,
                selected,
            )
            QMessageBox.information(
                self,
                'Privileges saved',
                f"Granted: {len(result['granted'])}\nRevoked: {len(result['revoked'])}",
            )
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, 'Could not save privileges', str(exc))


class UsersPage(QWidget):
    def __init__(self, current_user=None):
        super().__init__()
        self.current_user = current_user
        self.auth = AuthenticationService()
        self.users = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        header = QHBoxLayout()
        title = QLabel('Users')
        title.setObjectName('pageTitle')
        header.addWidget(title)
        header.addStretch()
        self.manage_btn = QPushButton('Manage privileges')
        self.manage_btn.setIcon(icon('shield'))
        self.manage_btn.clicked.connect(self.manage_privileges)
        header.addWidget(self.manage_btn)
        self.role_btn = QPushButton('Change role')
        self.role_btn.setIcon(icon('settings'))
        self.role_btn.clicked.connect(self.change_role)
        header.addWidget(self.role_btn)
        self.delete_user_btn = QPushButton('Delete user')
        self.delete_user_btn.setIcon(icon('delete'))
        self.delete_user_btn.clicked.connect(self.delete_user)
        header.addWidget(self.delete_user_btn)
        add = QPushButton('Add user')
        add.setObjectName('primary')
        add.setIcon(icon('plus'))
        add.clicked.connect(self.add_user)
        header.addWidget(add)
        layout.addLayout(header)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['Username', 'Full name', 'Role', 'Phone', 'Status', 'Privileges'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        setup_table(self.table)
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.table.cellDoubleClicked.connect(lambda row, _col: self._open_privileges(row))
        layout.addWidget(self.table, 1)
        self.load()
        self._update_actions()

    def _can_manage(self):
        return bool(
            self.current_user
            and self.current_user.is_admin()
            and self.current_user.has_permission('MANAGE_PERMISSIONS')
        )

    def _update_actions(self):
        allowed=self._can_manage() and self._selected_user() is not None
        self.manage_btn.setEnabled(allowed)
        self.role_btn.setEnabled(allowed)
        selected = self._selected_user()
        self.delete_user_btn.setEnabled(bool(
            self.current_user and self.current_user.is_admin()
            and self.current_user.has_permission('MANAGE_USERS')
            and selected and selected.id != self.current_user.id
        ))

    def _selected_user(self):
        row = self.table.currentRow()
        return self.users[row] if 0 <= row < len(self.users) else None

    def load(self):
        self.users = self.auth.get_all_users()
        self.table.setRowCount(len(self.users))
        for r, user in enumerate(self.users):
            privilege_count = len(self.auth.get_user_permissions(user.id))
            values = [
                user.username,
                user.full_name,
                user.role.name if user.role else '',
                user.phone or '',
                'ACTIVE' if user.is_active else 'DISABLED',
                f'{privilege_count} privileges',
            ]
            for c, value in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(str(value)))
        self._update_actions()

    def add_user(self):
        if not self.current_user or not self.current_user.is_admin() or not self.current_user.has_permission('MANAGE_USERS'):
            QMessageBox.warning(self, 'Permission denied', 'Only an authorized administrator can create users.')
            return
        dialog = UserCreateDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            data = dialog.values()
            user_id = self.auth.create_user(
                data['username'],
                data['password'],
                data['full_name'],
                data['role_id'],
                data['email'],
                data['phone'],
            )
            AuditService().log_user_creation(user_id, self.current_user.id)
            self.load()
            QMessageBox.information(self, 'User created', f"{data['full_name']} was created successfully.")
        except Exception as exc:
            QMessageBox.critical(self, 'Could not create user', str(exc))

    def change_role(self):
        user=self._selected_user()
        if not user:
            QMessageBox.information(self,'Select a user','Select a user first.')
            return
        if not self._can_manage():
            QMessageBox.warning(self,'Permission denied','Only an authorized administrator can change user roles.')
            return
        if user.id == self.current_user.id:
            QMessageBox.warning(self,'Protected account','The currently logged-in administrator role cannot be changed here.')
            return
        roles=self.auth.get_all_roles()
        labels=[r.name.replace('_',' ').title() for r in roles]
        current_index=next((i for i,r in enumerate(roles) if r.id==user.role_id),0)
        choice,ok=QInputDialog.getItem(self,'Change role',f'Role for {user.full_name}:',labels,current_index,False)
        if not ok:return
        role=roles[labels.index(choice)]
        try:
            self.auth.change_user_role(self.current_user.id,user.id,role.id)
            self.load()
            QMessageBox.information(self,'Role updated',f'{user.full_name} is now {role.name.replace("_"," ").title()}.')
        except Exception as exc:
            QMessageBox.critical(self,'Could not change role',str(exc))

    def _open_privileges(self, row):
        if not self._can_manage():
            return
        user = self.users[row] if 0 <= row < len(self.users) else None
        if user:
            dialog = UserPrivilegesDialog(self.current_user, user, self)
            if dialog.exec() == QDialog.Accepted:
                self.load()

    def delete_user(self):
        user = self._selected_user()
        if not user:
            QMessageBox.information(self, 'Select a user', 'Select a user first.')
            return
        if not self.current_user or not self.current_user.is_admin() or not self.current_user.has_permission('MANAGE_USERS'):
            QMessageBox.warning(self, 'Permission denied', 'Only an authorized administrator can delete users.')
            return
        if user.id == self.current_user.id:
            QMessageBox.warning(self, 'Protected account', 'The currently logged-in administrator cannot be deleted.')
            return
        answer = QMessageBox.warning(
            self, 'Delete user access',
            f'Delete {user.username}? This permanently disables their login and removes their permissions. Historical records will be preserved.',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        reason, ok = QInputDialog.getText(self, 'Delete user access', 'Reason (required):')
        if not ok or not reason.strip():
            return
        try:
            self.auth.delete_user(self.current_user.id, user.id, reason.strip())
            self.load()
            QMessageBox.information(self, 'User deleted', f'Access for {user.username} has been disabled.')
        except Exception as exc:
            QMessageBox.critical(self, 'Could not delete user', str(exc))

    def manage_privileges(self):
        user = self._selected_user()
        if not user:
            QMessageBox.information(self, 'Select a user', 'Select a user first.')
            return
        self._open_privileges(self.table.currentRow())


class PermissionsPage(QWidget):
    """Read-only permission catalogue. Per-user privileges are managed from Users."""
    def __init__(self):
        super().__init__()
        self.service = PermissionService()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 28)
        layout.setSpacing(14)
        title = QLabel('Permissions')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        desc = QLabel('Permission catalogue. Use Users > Manage privileges to grant access to individual users.')
        desc.setObjectName('muted')
        layout.addWidget(desc)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setStyleSheet(f"background:{COLORS['canvas']};")
        body_layout = QVBoxLayout(body)
        body_layout.setSpacing(10)
        groups = {}
        for perm in self.service.get_all_permissions():
            groups.setdefault(perm.category or 'OTHER', []).append(perm)
        for category, permissions in groups.items():
            frame, frame_layout = panel(category.title(), f'{len(permissions)} permissions')
            table = QTableWidget(len(permissions), 2)
            table.setHorizontalHeaderLabels(['Permission', 'Description'])
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            setup_table(table)
            for row, perm in enumerate(permissions):
                table.setItem(row, 0, QTableWidgetItem(perm.code.replace('_', ' ').title()))
                table.setItem(row, 1, QTableWidgetItem(perm.description or ''))
            frame_layout.addWidget(table)
            body_layout.addWidget(frame)
        body_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

class SettingsPage(QWidget):
    def __init__(self, user=None):
        super().__init__(); self.user=user; from database.db import get_database_manager; self.db=get_database_manager(); l=QVBoxLayout(self); l.setContentsMargins(28,22,28,28); l.setSpacing(14); t=QLabel('Settings'); t.setObjectName('pageTitle'); l.addWidget(t); d=QLabel('Manage business defaults and offline-first operating preferences.'); d.setObjectName('muted'); l.addWidget(d)
        grid=QGridLayout(); grid.setSpacing(12); l.addLayout(grid)
        company,company_layout=panel('Company profile','Shown on receipts and invoices'); form=QFormLayout(); self.shop=QLineEdit(); self.shop.setPlaceholderText('Online Motor Spares'); form.addRow('Company name',self.shop); self.tagline=QLineEdit(); self.tagline.setPlaceholderText('Business tagline'); form.addRow('Tagline',self.tagline); self.phone=QLineEdit(); self.phone.setPlaceholderText('Contact phone'); form.addRow('Contact phone',self.phone); company_layout.addLayout(form); grid.addWidget(company,0,0)
        operations,operations_layout=panel('Sales and currency','Defaults for new transactions'); form=QFormLayout(); self.currency=QComboBox(); self.currency.addItems(CurrencyService.CODES); form.addRow('Default currency',self.currency); self.tax=QLineEdit(); self.tax.setPlaceholderText('15'); form.addRow('VAT rate (%)',self.tax); self.receipt=QCheckBox('Print receipt after completed sale'); form.addRow('',self.receipt); operations_layout.addLayout(form); grid.addWidget(operations,0,1)
        sync_panel,sync_layout=panel('Offline and synchronization','Local-first reliability'); form=QFormLayout(); self.sync_mode=QComboBox(); self.sync_mode.addItems(['Offline-first','Online preferred']); form.addRow('Operating mode',self.sync_mode); self.endpoint=QLineEdit(); self.endpoint.setPlaceholderText('Optional sync endpoint'); form.addRow('Sync endpoint',self.endpoint); sync_layout.addLayout(form); grid.addWidget(sync_panel,1,0)
        printer,printer_layout=panel('Printer and backup','Hardware and data safety'); form=QFormLayout(); self.printer=QLineEdit(); self.printer.setPlaceholderText('Default printer name'); form.addRow('Receipt printer',self.printer); self.backup=QCheckBox('Remind me to back up the database'); form.addRow('',self.backup); printer_layout.addLayout(form); grid.addWidget(printer,1,1)
        if user and user.is_admin():
            cleanup,cleanup_layout=panel('System Reset / Data Cleanup','Backup-first administrative cleanup; financial history is voided, not deleted'); cleanup_btn=QPushButton('System Reset / Data Cleanup'); cleanup_btn.setIcon(icon('warning')); cleanup_btn.clicked.connect(self.run_cleanup); cleanup_layout.addWidget(cleanup_btn); l.addWidget(cleanup)
        actions=QHBoxLayout(); actions.addStretch(); b=QPushButton('Save settings'); b.setObjectName('primary'); b.setIcon(icon('settings')); b.clicked.connect(self.save); actions.addWidget(b); l.addLayout(actions); l.addStretch(); self.load()
    def load(self):
        rows=self.db.execute_query('SELECT key,value FROM settings'); values={x['key']:x['value'] for x in rows}; self.shop.setText(values.get('company_name') or 'Online Motor Spares'); self.tagline.setText(values.get('tagline','')); self.phone.setText(values.get('company_phone','')); self.currency.setCurrentText(values.get('currency') or configured_currency()); self.tax.setText(values.get('tax_rate','15')); self.sync_mode.setCurrentText(values.get('sync_mode','Offline-first')); self.endpoint.setText(values.get('sync_endpoint','')); self.printer.setText(values.get('printer_name','')); self.receipt.setChecked(values.get('auto_print','0')=='1'); self.backup.setChecked(values.get('backup_reminder','0')=='1')
    def save(self):
        try:
            values=[('company_name',self.shop.text().strip()),('tagline',self.tagline.text().strip()),('company_phone',self.phone.text().strip()),('currency',self.currency.currentText()),('tax_rate',self.tax.text().strip() or '15'),('sync_mode',self.sync_mode.currentText()),('sync_endpoint',self.endpoint.text().strip()),('printer_name',self.printer.text().strip()),('auto_print','1' if self.receipt.isChecked() else '0'),('backup_reminder','1' if self.backup.isChecked() else '0')]
            for key,value in values:self.db.execute_update("INSERT INTO settings(key,value,data_type) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",(key,value,'string'))
            emit_change('SETTINGS', {'currency': self.currency.currentText()})
            QMessageBox.information(self,'Settings saved','Your preferences were saved successfully.')
        except Exception as e:QMessageBox.critical(self,'Could not save settings',str(e))
    def run_cleanup(self):
        if not self.user or not self.user.is_admin(): QMessageBox.warning(self,'Permission denied','Only an administrator can run system cleanup.'); return
        options=['Clear inventory (archive active products)','Clear customers (archive customers and vehicles)','Clear quotations (cancel open quotations)','Clear sales/invoices (void completed invoices and restore stock)','Full system reset (all of the above)']
        choice,ok=QInputDialog.getItem(self,'System Reset / Data Cleanup','Choose data cleanup:',options,0,False)
        if not ok:return
        confirm,ok=QInputDialog.getText(self,'Confirm system cleanup','Type RESET SYSTEM to create a backup and continue:')
        if not ok or confirm.strip().upper() != 'RESET SYSTEM':return
        option={'Clear inventory (archive active products)':'inventory','Clear customers (archive customers and vehicles)':'customers','Clear quotations (cancel open quotations)':'quotations','Clear sales/invoices (void completed invoices and restore stock)':'sales_invoices','Full system reset (all of the above)':'full'}[choice]
        try:
            from services.admin_cleanup_service import AdminCleanupService
            result=AdminCleanupService().cleanup(option,self.user.id)
            QMessageBox.information(self,'Cleanup completed',f"Backup: {result['backup']}\nArchived products: {result['archived_products']}\nArchived customers: {result['archived_customers']}\nCancelled quotations: {result['cancelled_quotes']}\nVoided invoices: {result['voided_invoices']}")
        except Exception as exc: QMessageBox.critical(self,'Cleanup failed',str(exc))

class CustomersPage(QWidget):
    def __init__(self):
        super().__init__(); self.sales=SalesService(); from database.db import get_database_manager; self.db=get_database_manager(); l=QVBoxLayout(self); l.setContentsMargins(28,24,28,24); h=QHBoxLayout(); t=QLabel('Customers'); t.setObjectName('pageTitle'); h.addWidget(t); h.addStretch(); self.search_box=QLineEdit(); self.search_box.setPlaceholderText('Search name, phone, email or city'); self.search_box.returnPressed.connect(self.load); h.addWidget(self.search_box); find=QPushButton('Search'); find.setIcon(icon('search')); find.clicked.connect(self.load); h.addWidget(find); add=QPushButton('Add customer'); add.setObjectName('primary'); add.setIcon(icon('plus')); add.clicked.connect(self.add); h.addWidget(add); l.addLayout(h); self.table=QTableWidget(0,5); self.table.setHorizontalHeaderLabels(['Name','Phone','Email','City','Edit']); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); setup_table(self.table); self.table.cellDoubleClicked.connect(self.edit); l.addWidget(self.table,1); self.load()
    def load(self):
        term=f"%{self.search_box.text().strip()}%"; rows=self.db.execute_query('SELECT id,name,phone,email,city FROM customers WHERE name LIKE ? OR phone LIKE ? OR email LIKE ? OR city LIKE ? ORDER BY name',(term,term,term,term)); self.rows=rows; self.table.setRowCount(len(rows))
        for r,x in enumerate(rows):
            for c,v in enumerate([x['name'],x['phone'] or '',x['email'] or '',x['city'] or '','Double-click to edit']):self.table.setItem(r,c,QTableWidgetItem(v))
    def add(self):
        name,ok=QInputDialog.getText(self,'Add customer','Customer name:')
        if not ok or not name.strip():return
        d=CustomerDialog(self.sales,self,current={'name': name.strip()})
        if d.exec()!=QDialog.Accepted:return
        values=d.values()
        try:self.sales.find_or_create_customer(values['name'],values.get('phone'),values.get('email'),values.get('vehicle_make'),values.get('vehicle_model'),values.get('vehicle_registration'),values.get('city')); self.load(); QMessageBox.information(self,'Saved','Customer saved successfully.')
        except Exception as e:QMessageBox.critical(self,'Could not save customer',str(e))
    def edit(self,row,column):
        customer=self.sales.get_customer(self.rows[row]['id'])
        if not customer:return
        d=CustomerDialog(self.sales,self,current=customer.to_dict())
        if d.exec()!=QDialog.Accepted:return
        values=d.values()
        try:self.sales.update_customer(customer.id,values['name'],values.get('phone'),values.get('email'),values.get('city'),values.get('vehicle_make'),values.get('vehicle_model'),values.get('vehicle_registration')); self.load()
        except Exception as e:QMessageBox.critical(self,'Could not update customer',str(e))

class PlaceholderPage(QWidget):
    def __init__(self,title,description):
        super().__init__(); l=QVBoxLayout(self); l.setContentsMargins(28,24,28,24); t=QLabel(title); t.setObjectName('pageTitle'); l.addWidget(t); d=QLabel(description); d.setObjectName('muted'); l.addWidget(d); p=QFrame(); p.setObjectName('panel'); pl=QVBoxLayout(p); pl.addWidget(QLabel('This workspace is connected to the existing backend services.')); pl.addStretch(); l.addWidget(p,1)

class MotorSparesPOSTestWindow(QMainWindow):
    logout_requested = Signal()

    def __init__(self,user=None):
        super().__init__(); self.user=user; self.setWindowTitle('Online Motor Spares POS - Michoe Tech Labs'); self.resize(1440,900); self.setMinimumSize(1100,680); self.setStyleSheet(STYLESHEET); self.products=ProductService(); self.inventory=InventoryService(); self.stack=QStackedWidget(); self.pages={}; self.nav={}; self.build(); self._setup_auto_sync(); subscribe_data_changed(self._on_data_changed)
    def build(self):
        c=QWidget(); c.setObjectName('canvas'); self.setCentralWidget(c); outer=QHBoxLayout(c); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0); side=QFrame(); side.setFixedWidth(244); side.setStyleSheet(f'background:{COLORS["nav"]};'); sl=QVBoxLayout(side); sl.setContentsMargins(18,24,18,18); brand=QLabel('MICHOE TECH LABS'); brand.setObjectName('brand'); sl.addWidget(brand); sub=QLabel('Online Motor Spares'); sub.setObjectName('brandSub'); sl.addWidget(sub); sl.addSpacing(24)
        entries=[]
        if self._can_access_dashboard():
            entries.append(('Dashboard', DashboardPage(self.products, self.user), 'dashboard'))
        entries.extend([('POS',POSPage(self.products,self.inventory,self.user),'cart'),('Inventory',InventoryPage(self.products,self.user),'package'),('Products',ProductsPage(self.products,self.user),'package'),('Invoices',InvoicesPage(self.user),'invoice'),('Returns',ReturnsPage(self.user),'return'),('Customers',CustomersPage(),'users'),('Reports',ReportsPage(self.user),'chart')])
        for name,page,ic in entries:self.add_nav(sl,name,page,ic)
        al=QLabel('ADMINISTRATION'); al.setStyleSheet(f'color:{COLORS["nav_muted"]};font-size:10px;font-weight:700;padding:16px 6px 6px;'); sl.addWidget(al)
        if self.user and (self.user.is_admin() or self.user.has_permission('MANAGE_USERS')):
            self.add_nav(sl,'Users',UsersPage(self.user),'users')
        if self.user and (self.user.is_admin() or self.user.has_permission('MANAGE_PERMISSIONS')):
            self.add_nav(sl,'Permissions',PermissionsPage(),'shield')
        if self.user and (self.user.is_admin() or self.user.has_permission('SYSTEM_SETTINGS')):
            self.add_nav(sl,'Settings',SettingsPage(self.user),'settings')
        if self.user and (self.user.is_admin() or self.user.has_permission('SYNC_DATA')):
            self.add_nav(sl,'Synchronization',SyncPage(self.user),'sync')
        sl.addStretch(); out=QPushButton('Logout'); out.setObjectName('nav'); out.setIcon(icon('logout')); out.clicked.connect(self.logout_requested.emit); sl.addWidget(out); outer.addWidget(side)
        content=QWidget(); cl=QVBoxLayout(content); cl.setContentsMargins(0,0,0,0); top=QFrame(); top.setFixedHeight(72); top.setStyleSheet('background:#FFFFFF;border-bottom:1px solid #E2E8F0;'); tl=QHBoxLayout(top); tl.setContentsMargins(28,0,24,0); self.header=QLabel('Dashboard' if 'Dashboard' in self.pages else 'POS'); self.header.setObjectName('sectionTitle'); tl.addWidget(self.header); tl.addStretch(); online=QLabel('ONLINE'); online.setObjectName('statusOnline'); tl.addWidget(online); who=QLabel(f'{self.user.full_name if self.user else "Administrator"}  |  {self.user.role.name if self.user and self.user.role else "ADMIN"}'); who.setObjectName('muted'); tl.addWidget(who); cl.addWidget(top); cl.addWidget(self.stack,1); outer.addWidget(content,1); self.go('Dashboard' if 'Dashboard' in self.pages else 'POS')
    def _setup_auto_sync(self):
        self._sync_running = False
        self._sync_service = SyncService()
        try:
            configured = float(self._sync_service.config.get('sync_interval', 60))
        except (TypeError, ValueError):
            configured = 60
        interval_ms = int(max(60, min(configured, 3600)) * 1000)
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(interval_ms)
        self._sync_timer.timeout.connect(self._auto_sync)
        self._sync_timer.start()
        QTimer.singleShot(1500, self._auto_sync)

    def _auto_sync(self):
        """Attempt synchronization in a daemon thread so the POS stays responsive."""
        if self._sync_running or not self._sync_service.server_configured():
            return
        self._sync_running = True

        def worker():
            try:
                self._sync_service.sync_now()
            except Exception:
                logger.exception('Automatic synchronization failed')
            finally:
                self._sync_running = False

        import threading
        threading.Thread(target=worker, name='POS-AutoSync', daemon=True).start()

    def add_nav(self,layout,name,page,icon_name=None):
        b=QPushButton(name); b.setObjectName('nav'); b.setCheckable(True); b.setIcon(icon(icon_name) if icon_name else QIcon()); b.setIconSize(QSize(18,18)); b.clicked.connect(lambda _,n=name:self.go(n)); layout.addWidget(b); self.nav[name]=b; self.pages[name]=page; self.stack.addWidget(page)
    def _can_access_dashboard(self):
        return bool(self.user and (self.user.is_admin() or self.user.has_permission('dashboard.view')))
    def go(self,name):
        if name == 'Dashboard' and not self._can_access_dashboard():
            QMessageBox.warning(self, 'Access denied', 'Access denied.')
            name = 'POS' if 'POS' in self.pages else next(iter(self.pages), None)
            if name is None: return False
        if name not in self.pages:
            QMessageBox.warning(self, 'Access denied', 'Access denied.')
            return False
        for n,b in self.nav.items():b.setChecked(n==name)
        self.header.setText(name); page=self.pages[name]; self.stack.setCurrentWidget(page)
        # Always show current data the moment a screen is opened, not
        # whatever was loaded when the app first started.
        self._refresh_page(page,f'navigate to {name}')
        return True
    def _on_data_changed(self,entity_type,detail):
        """Fired the instant any change happens anywhere in the system
        (a sale, a stock edit, a spreadsheet import, or an update pulled
        from the sync server). Keep whatever screen is currently open
        showing live data without the user having to do anything."""
        current = self.stack.currentWidget()
        for page in dict.fromkeys(self.pages.values()):
            self._refresh_page(page,f'{entity_type} change')
    @staticmethod
    def _refresh_page(page,context):
        method = getattr(page, 'refresh', None)
        if not callable(method):
            method = getattr(page, 'load', None)
        if callable(method):
            try:method()
            except Exception:logger.exception('Live refresh (%s) failed for %s',context,page.__class__.__name__)

def launch():
    app=QApplication.instance() or QApplication(sys.argv); app.setStyle('Fusion')
    login=LoginDialog()
    if login.exec()!=QDialog.Accepted:
        return 0

    window = MotorSparesPOSTestWindow(login.user)

    def logout():
        nonlocal window
        if window.user:
            AuthenticationService().logout(window.user.id)
        window.hide()
        next_login = LoginDialog()
        if next_login.exec() == QDialog.Accepted:
            window.close()
            window.deleteLater()
            window = MotorSparesPOSTestWindow(next_login.user)
            window.logout_requested.connect(logout)
            window.show()
        else:
            app.quit()

    window.logout_requested.connect(logout)
    window.show()
    return app.exec()

if __name__=='__main__':sys.exit(launch())
