# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'main_window.ui'
##
## Created by: Qt User Interface Compiler version 6.10.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QAction, QBrush, QColor, QConicalGradient,
    QCursor, QFont, QFontDatabase, QGradient,
    QIcon, QImage, QKeySequence, QLinearGradient,
    QPainter, QPalette, QPixmap, QRadialGradient,
    QTransform)
from PySide6.QtWidgets import (QApplication, QMainWindow, QMenu, QMenuBar,
    QSizePolicy, QWidget)

from PySide6QtAds import CDockManager

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1280, 800)
        self.actionOpenLogFolder = QAction(MainWindow)
        self.actionOpenLogFolder.setObjectName(u"actionOpenLogFolder")
        self.actionAbout = QAction(MainWindow)
        self.actionAbout.setObjectName(u"actionAbout")
        self.dockManager = CDockManager(MainWindow)
        self.dockManager.setObjectName(u"dockManager")
        self.dockManager.setGeometry(QRect(0, 0, 1280, 779))
        MainWindow.setCentralWidget(self.dockManager)
        self.menuBar = QMenuBar(MainWindow)
        self.menuBar.setObjectName(u"menuBar")
        self.menuBar.setGeometry(QRect(0, 0, 1280, 21))
        self.menuApplication = QMenu(self.menuBar)
        self.menuApplication.setObjectName(u"menuApplication")
        MainWindow.setMenuBar(self.menuBar)

        self.menuBar.addAction(self.menuApplication.menuAction())
        self.menuApplication.addAction(self.actionOpenLogFolder)
        self.menuApplication.addSeparator()
        self.menuApplication.addAction(self.actionAbout)

        self.retranslateUi(MainWindow)

        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"VI - Toolbox", None))
        self.actionOpenLogFolder.setText(QCoreApplication.translate("MainWindow", u"Open Log Folder", None))
        self.actionAbout.setText(QCoreApplication.translate("MainWindow", u"About", None))
        self.menuApplication.setTitle(QCoreApplication.translate("MainWindow", u"Application", None))
    # retranslateUi

