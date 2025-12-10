# config.py

"""
ملف التكوين لتشغيل الميزات الجديدة
"""

from core.settings_manager import SettingsManager
from core.state_manager import StateManager
from core.logger import Logger
from core.strategy_engine import StrategyEngine
from core.market_data_manager import MarketDataManager
try:
    from core.backtester import Backtester
except Exception:
    Backtester = None  # type: ignore
from core.multi_timeframe_analyzer import MultiTimeframeAnalyzer


def setup_backtesting() -> Backtester:
    """
    إعداد نظام Backtesting
    """
    # إنشاء المديرين
    settings = SettingsManager()
    logger = Logger()
    
    # إنشاء Backtester
    backtester = Backtester(
        settings_manager=settings,
        logger=logger
    )
    
    return backtester


def setup_multi_timeframe_analyzer() -> MultiTimeframeAnalyzer:
    """
    إعداد محلل الأطر الزمنية المتعددة
    """
    # إنشاء المديرين
    settings = SettingsManager()
    state = StateManager()
    logger = Logger()
    
    # إنشاء المحركين
    strategy = StrategyEngine(settings, logger)
    market_data = MarketDataManager(settings, state, logger)
    
    # إنشاء المحلل
    analyzer = MultiTimeframeAnalyzer(
        strategy_engine=strategy,
        market_data=market_data,
        logger=logger
    )
    
    return analyzer


def run_backtest_example():
    """
    مثال على استخدام Backtester
    """
    backtester = setup_backtesting()
    
    # تحميل بيانات تاريخية (مثال)
    success = backtester.load_historical_data_from_binance(
        symbol="BTCUSDT",
        start_date="2024-01-01",
        end_date="2024-01-31",
        interval="15m"
    )
    
    if success:
        # إنشاء استراتيجية بسيطة
        from core.strategy_engine import StrategyEngine
        from core.settings_manager import SettingsManager
        from core.logger import Logger
        
        settings = SettingsManager()
        logger = Logger()
        strategy = StrategyEngine(settings, logger)
        
        # تشغيل Backtest
        result = backtester.run_backtest(
            symbol="BTCUSDT",
            strategy=strategy,
            initial_capital=1000.0,
            trade_risk_pct=2.0
        )
        
        # عرض النتائج
        print(f"Backtest Results for {result.symbol}:")
        print(f"  Total Return: {result.total_return_pct:.2f}%")
        print(f"  Sharpe Ratio: {result.sharpe_ratio:.3f}")
        print(f"  Max Drawdown: {result.max_drawdown_pct:.2f}%")
        print(f"  Win Rate: {result.win_rate:.1f}%")
        print(f"  Total Trades: {result.total_trades}")
        
        # تصدير النتائج
        backtester.export_results(result)


def run_multi_timeframe_analysis_example():
    """
    مثال على استخدام محلل الأطر الزمنية المتعددة
    """
    analyzer = setup_multi_timeframe_analyzer()
    
    # تحليل رمز معين
    analysis = analyzer.analyze_confluence("BTCUSDT")
    
    if analysis:
        print(f"Confluence Analysis for {analysis.symbol}:")
        print(f"  Overall Signal: {analysis.overall_signal}")
        print(f"  Overall Score: {analysis.overall_score:.1f}")
        print(f"  Confidence: {analysis.confidence:.1%}")
        print(f"  Recommendation: {analysis.recommendation}")
        print(f"  Risk Level: {analysis.risk_level}")
        print(f"  Suggested Action: {analysis.suggested_action}")
        print(f"  Position Size: {analysis.position_size_pct:.1%}")
        print(f"  Stop Loss: {analysis.stop_loss_pct:.1f}%")
        print(f"  Take Profit: {analysis.take_profit_pct:.1f}%")
        
        # تصدير التحليل
        analyzer.export_analysis(analysis)


if __name__ == "__main__":
    print("Testing Backtester...")
    run_backtest_example()
    
    print("\n" + "="*50 + "\n")
    
    print("Testing Multi-Timeframe Analyzer...")
    run_multi_timeframe_analysis_example()