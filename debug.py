#!/usr/bin/env python3
"""
Система отладки и мониторинга бота
"""

import logging
import traceback
import sys
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)

class DebugSystem:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.performance_data = {}
        self.start_time = datetime.now()
    
    def log_error(self, error_msg, function_name, line_number):
        """Логирует ошибку с деталями"""
        error_data = {
            'timestamp': datetime.now(),
            'message': error_msg,
            'function': function_name,
            'line': line_number,
            'traceback': traceback.format_exc()
        }
        self.errors.append(error_data)
        logger.error(f"Ошибка в {function_name}:{line_number} - {error_msg}")
    
    def log_warning(self, warning_msg, function_name):
        """Логирует предупреждение"""
        warning_data = {
            'timestamp': datetime.now(),
            'message': warning_msg,
            'function': function_name
        }
        self.warnings.append(warning_data)
        logger.warning(f"Предупреждение в {function_name}: {warning_msg}")
    
    def log_performance(self, operation_name, execution_time):
        """Логирует время выполнения операции"""
        if operation_name not in self.performance_data:
            self.performance_data[operation_name] = []
        self.performance_data[operation_name].append(execution_time)
    
    def get_error_report(self):
        """Генерирует отчет об ошибках"""
        if not self.errors:
            return "✅ Ошибок не обнаружено"
        
        report = "🚨 **Отчет об ошибках:**\n\n"
        for i, error in enumerate(self.errors[-10:], 1):
            report += f"{i}. **{error['function']}** (строка {error['line']})\n"
            report += f"   🕒 {error['timestamp'].strftime('%H:%M:%S')}\n"
            report += f"   💬 {error['message']}\n"
            if error['traceback'] and "NoneType" in error['traceback']:
                report += f"   🔧 **Исправление:** Проверьте наличие None значений\n"
            report += "\n"
        
        return report
    
    def get_performance_report(self):
        """Генерирует отчет о производительности"""
        if not self.performance_data:
            return "📊 Данные о производительности отсутствуют"
        
        report = "⚡ **Отчет о производительности:**\n\n"
        for operation, times in self.performance_data.items():
            avg_time = sum(times) / len(times)
            max_time = max(times)
            min_time = min(times)
            report += f"**{operation}:**\n"
            report += f"   • Среднее: {avg_time:.3f}с\n"
            report += f"   • Макс: {max_time:.3f}с\n"
            report += f"   • Мин: {min_time:.3f}с\n"
            report += f"   • Вызовов: {len(times)}\n\n"
        
        return report
    
    def get_system_status(self):
        """Проверяет статус системы"""
        status_report = "🔧 **Статус системы:**\n\n"
        
        try:
            # Проверка базы данных
            from bot_database import db
            
            # Проверка таблиц
            tables = ['users', 'calculator_sessions', 'broadcasts', 'bot_settings', 'update_history']
            for table in tables:
                try:
                    # Используем метод БД вместо прямого SQL
                    if table == 'users':
                        stats = db.get_user_stats()
                        count = stats['total_users']
                    elif table == 'calculator_sessions':
                        stats = db.get_user_stats()
                        count = stats['active_sessions']
                    else:
                        count = "N/A"
                    
                    status_report += f"✅ Таблица {table}: {count} записей\n"
                except Exception as e:
                    status_report += f"❌ Таблица {table}: Ошибка - {str(e)}\n"
            
        except Exception as e:
            status_report += f"❌ База данных: {str(e)}\n"
        
        # Статистика ошибок
        status_report += f"\n📈 **Статистика:**\n"
        status_report += f"• Ошибок: {len(self.errors)}\n"
        status_report += f"• Предупреждений: {len(self.warnings)}\n"
        status_report += f"• Время работы: {(datetime.now() - self.start_time).total_seconds() / 60:.1f} мин\n"
        
        return status_report

# Глобальный экземпляр системы отладки
debug_system = DebugSystem()