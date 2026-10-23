# -*- coding: utf-8 -*-
"""按「一页一件事」拆分的六个页面。"""
from pages.photo import PhotoPage
from pages.train_settings import TrainSettingsPage
from pages.run import RunPage
from pages.history import HistoryPage
from pages.settings import SettingsPage
from pages.log import LogPage

__all__ = ["PhotoPage", "TrainSettingsPage", "RunPage",
           "HistoryPage", "SettingsPage", "LogPage"]
