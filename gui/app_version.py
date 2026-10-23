# -*- coding: utf-8 -*-
"""版本号的唯一来源。

放在 gui/ 下是因为安装包只分发 gui/、tools/、sample/ 等运行期文件，不分发
installer/ —— 版本号写在这里，界面标题、日志、诊断包和打包脚本才读得到同一份。
installer/build_setup.ps1 会解析本文件来生成版本资源与产物文件名。
"""

APP_VERSION = "2.4.0"
