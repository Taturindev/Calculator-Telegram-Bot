#!/usr/bin/env python3
import sys
import subprocess
import importlib.util
import os

def check_python_version():
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print(f"❌ Требуется Python 3.8+! У вас: {version.major}.{version.minor}.{version.micro}")
        print("📥 Скачайте с: https://www.python.org/downloads/")
        return False
    print(f"✅ Python {version.major}.{version.minor}.{version.micro} - OK")
    return True

def is_module_available(module_name):
    return importlib.util.find_spec(module_name) is not None

def install_package(package):
    try:
        print(f"🔄 Устанавливаю {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])
        print(f"✅ {package} установлен")
        return True
    except Exception as e:
        print(f"❌ Ошибка установки {package}: {e}")
        return False

def main():
    print("🔍 Проверяю систему...")
    
    if not check_python_version():
        return False
    
    print("\n🔍 Проверяю зависимости...")
    
    required_packages = ["aiogram==3.2.0", "aiofiles==23.2.1"]
    all_installed = True
    
    for package in required_packages:
        package_name = package.split('==')[0]
        if not is_module_available(package_name):
            if not install_package(package):
                all_installed = False
        else:
            print(f"✅ {package_name} установлен")
    
    if all_installed:
        print("\n🎉 Все зависимости установлены!")
        return True
    else:
        print("\n❌ Ошибка установки зависимостей!")
        print("pip install aiogram==3.2.0 aiofiles==23.2.1")
        return False

if __name__ == "__main__":
    if main():
        print("🚀 Запускаю бота...")
        try:
            # Прямой запуск main.py чтобы избежать циклических импортов
            os.system(f'"{sys.executable}" main.py')
        except Exception as e:
            print(f"❌ Ошибка запуска: {e}")
            input("Нажмите Enter для выхода...")
    else:
        input("Нажмите Enter для выхода...")
        sys.exit(1)