# core/multi_timeframe_analyzer.py

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import threading

from core.logger import Logger
from core.strategy_engine import StrategyEngine
from core.market_data_manager import MarketDataManager, Candle


@dataclass
class TimeframeSignal:
    """إشارة من إطار زمني معين"""
    timeframe: str
    symbol: str
    score: float
    signal: str  # BULLISH, BEARISH, NEUTRAL
    confidence: float  # 0-1
    indicators: Dict[str, Any]
    trend_strength: float  # قوة الترند 0-1
    volatility: float  # التقلب 0-1


@dataclass
class ConfluenceAnalysis:
    """تحليل التقاء الإشارات"""
    symbol: str
    overall_score: float
    overall_signal: str  # STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL
    confidence: float
    timeframe_signals: Dict[str, TimeframeSignal]
    confluence_factors: Dict[str, float]  # عوامل التقاء
    recommendation: str
    risk_level: str  # LOW, MEDIUM, HIGH
    suggested_action: str  # ENTRY, EXIT, HOLD, PARTIAL_EXIT
    position_size_pct: float  # حجم المركز المقترح (نسبة من رأس المال)
    stop_loss_pct: float  # نسبة وقف الخسارة المقترحة
    take_profit_pct: float  # نسبة جني الأرباح المقترحة


class MultiTimeframeAnalyzer:
    """
    محلل متعدد الأطر الزمنية
    يحلل إشارات من أطر زمنية مختلفة ويعطي توصية موحدة
    """
    
    # أوزان الأطر الزمنية (تستند لأهمية كل إطار)
    TIMEFRAME_WEIGHTS = {
        # إطار أساسي للتداول اليومي
        "1m": 0.05,    # للـ scalping فقط
        "5m": 0.10,    # دخول/خروج سريع
        "15m": 0.20,   # الإطار الأساسي للتداول
        "1h": 0.25,    # اتجاه متوسط المدى
        "4h": 0.20,    # اتجاه طويل المدى
        "1d": 0.15,    # الاتجاه العام
        "1w": 0.05,    # اتجاه طويل جداً
    }
    
    # مستويات التقاء الإشارات
    CONFLUENCE_LEVELS = {
        "VERY_HIGH": 0.8,    # تقاء قوي جداً
        "HIGH": 0.7,         # تقاء قوي
        "MEDIUM": 0.5,       # تقاء متوسط
        "LOW": 0.3,          # تقاء ضعيف
        "VERY_LOW": 0.1,     # تقاء ضعيف جداً
    }
    
    def __init__(
        self,
        strategy_engine: StrategyEngine,
        market_data: MarketDataManager,
        logger: Optional[Logger] = None
    ) -> None:
        self.strategy = strategy_engine
        self.market_data = market_data
        self.logger = logger or Logger()
        
        # كاش للتحليلات السابقة
        self._analysis_cache: Dict[str, ConfluenceAnalysis] = {}
        self._signal_cache: Dict[Tuple[str, str], TimeframeSignal] = {}
        
        # أقفال للخيوط
        self._cache_lock = threading.RLock()
        self._analysis_lock = threading.RLock()
        
        # إعدادات التحليل
        self.min_timeframes_for_analysis = 3
        self.confidence_threshold = 0.6  # حد الثقة للتوصية
        self.cache_ttl_seconds = 60  # وقت صلاحية الكاش
        
        self.logger.info("MultiTimeframeAnalyzer initialized")
    
    # ====================== التحليل الرئيسي ======================
    
    def analyze_confluence(
        self,
        symbol: str,
        timeframes: Optional[List[str]] = None,
        use_cache: bool = True
    ) -> Optional[ConfluenceAnalysis]:
        """
        تحليل التقاء الإشارات من أطر زمنية متعددة
        """
        symbol = symbol.upper()
        
        try:
            # التحقق من الكاش إذا طُلب
            if use_cache:
                with self._cache_lock:
                    if symbol in self._analysis_cache:
                        analysis = self._analysis_cache[symbol]
                        # التحقق من صلاحية الكاش
                        if self._is_cache_valid(analysis):
                            self.logger.debug(f"Using cached analysis for {symbol}")
                            return analysis
            
            # تحديد الأطر الزمنية للتحليل
            if timeframes is None:
                timeframes = self._get_available_timeframes()
            
            if len(timeframes) < self.min_timeframes_for_analysis:
                self.logger.warning(
                    f"Insufficient timeframes for {symbol}. "
                    f"Got {len(timeframes)}, need at least {self.min_timeframes_for_analysis}"
                )
                return None
            
            # جمع الإشارات من كل إطار زمني
            timeframe_signals = {}
            valid_signals_count = 0
            
            for tf in timeframes:
                signal = self._analyze_timeframe(symbol, tf)
                if signal:
                    timeframe_signals[tf] = signal
                    valid_signals_count += 1
            
            if valid_signals_count < self.min_timeframes_for_analysis:
                self.logger.warning(
                    f"Not enough valid signals for {symbol}. "
                    f"Got {valid_signals_count}, need at least {self.min_timeframes_for_analysis}"
                )
                return None
            
            # حساب التحليل الموحد
            analysis = self._calculate_confluence(symbol, timeframe_signals)
            
            # حفظ في الكاش
            with self._cache_lock:
                self._analysis_cache[symbol] = analysis
            
            self.logger.info(
                f"Confluence analysis for {symbol}: {analysis.overall_signal} "
                f"(score: {analysis.overall_score:.1f}, confidence: {analysis.confidence:.1%})"
            )
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"Confluence analysis failed for {symbol}: {e}")
            return None
    
    def _analyze_timeframe(
        self,
        symbol: str,
        timeframe: str
    ) -> Optional[TimeframeSignal]:
        """
        تحليل إطار زمني فردي
        """
        try:
            # التحقق من الكاش أولاً
            cache_key = (symbol, timeframe)
            with self._cache_lock:
                if cache_key in self._signal_cache:
                    cached_signal = self._signal_cache[cache_key]
                    if self._is_signal_cache_valid(cached_signal):
                        return cached_signal
            
            # الحصول على بيانات الشموع
            candles = self.market_data.get_candles(symbol, timeframe)
            if not candles or len(candles) < 20:
                self.logger.debug(f"Insufficient candles for {symbol} {timeframe}")
                return None
            
            # استخراج الأسعار
            closes = [candle.close for candle in candles]
            highs = [candle.high for candle in candles]
            lows = [candle.low for candle in candles]
            
            if not closes:
                return None
            
            current_price = closes[-1]
            
            # حساب المؤشرات
            indicators = self._calculate_timeframe_indicators(
                closes, highs, lows, current_price
            )
            
            # تحديد الإشارة
            signal, score = self._determine_timeframe_signal(indicators)
            
            # حساب الثقة
            confidence = self._calculate_signal_confidence(indicators, score)
            
            # حساب قوة الترند
            trend_strength = self._calculate_trend_strength(indicators)
            
            # حساب التقلب
            volatility = self._calculate_volatility(closes)
            
            # إنشاء كائن الإشارة
            timeframe_signal = TimeframeSignal(
                timeframe=timeframe,
                symbol=symbol,
                score=score,
                signal=signal,
                confidence=confidence,
                indicators=indicators,
                trend_strength=trend_strength,
                volatility=volatility
            )
            
            # حفظ في الكاش
            with self._cache_lock:
                self._signal_cache[cache_key] = timeframe_signal
            
            return timeframe_signal
            
        except Exception as e:
            self.logger.debug(f"Timeframe analysis failed for {symbol} {timeframe}: {e}")
            return None
    
    # ====================== حساب المؤشرات ======================
    
    def _calculate_timeframe_indicators(
        self,
        closes: List[float],
        highs: List[float],
        lows: List[float],
        current_price: float
    ) -> Dict[str, Any]:
        """
        حساب المؤشرات الفنية للإطار الزمني
        """
        indicators = {}
        
        try:
            # RSI
            if len(closes) >= 14:
                indicators['rsi'] = self._calculate_rsi(closes[-14:])
            
            # Moving Averages
            if len(closes) >= 50:
                indicators['sma_20'] = sum(closes[-20:]) / 20
                indicators['sma_50'] = sum(closes[-50:]) / 50
                indicators['ema_12'] = self._calculate_ema(closes, 12)
                indicators['ema_26'] = self._calculate_ema(closes, 26)
            
            # MACD
            if len(closes) >= 26:
                macd_line, signal_line, histogram = self._calculate_macd(closes)
                indicators['macd'] = {
                    'line': macd_line,
                    'signal': signal_line,
                    'histogram': histogram,
                    'crossover': macd_line > signal_line
                }
            
            # Bollinger Bands
            if len(closes) >= 20:
                bb_upper, bb_middle, bb_lower = self._calculate_bollinger_bands(closes)
                indicators['bollinger'] = {
                    'upper': bb_upper,
                    'middle': bb_middle,
                    'lower': bb_lower,
                    'position': self._get_bb_position(current_price, bb_upper, bb_lower)
                }
            
            # Support and Resistance
            if len(highs) >= 20 and len(lows) >= 20:
                indicators['support_resistance'] = self._identify_support_resistance(highs, lows)
            
            # Volume (إذا كان متاحاً)
            # indicators['volume_trend'] = self._analyze_volume_trend(volumes)
            
            # Price Action
            indicators['price_action'] = self._analyze_price_action(closes)
            
            # Trend Direction
            indicators['trend_direction'] = self._determine_trend_direction(closes)
            
            # Momentum
            indicators['momentum'] = self._calculate_momentum(closes)
            
        except Exception as e:
            self.logger.debug(f"Indicator calculation error: {e}")
        
        return indicators
    
    def _calculate_rsi(self, prices: List[float]) -> float:
        """حساب RSI"""
        if len(prices) < 2:
            return 50.0
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / len(gains)
        avg_loss = sum(losses) / len(losses)
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return max(0.0, min(100.0, rsi))
    
    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """حساب EMA"""
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        
        return ema
    
    def _calculate_macd(
        self,
        prices: List[float]
    ) -> Tuple[float, float, float]:
        """حساب MACD"""
        if len(prices) < 26:
            return 0.0, 0.0, 0.0
        
        # MACD الخطي = EMA 12 - EMA 26
        ema_12 = self._calculate_ema(prices, 12)
        ema_26 = self._calculate_ema(prices, 26)
        macd_line = ema_12 - ema_26
        
        # خط الإشارة = EMA 9 من MACD
        # نحتاج إلى حساب MACD للفترة السابقة
        macd_values = []
        for i in range(len(prices) - 26 + 1):
            window = prices[i:i+26]
            if len(window) >= 26:
                ema_12_window = self._calculate_ema(window, 12)
                ema_26_window = self._calculate_ema(window, 26)
                macd_values.append(ema_12_window - ema_26_window)
        
        if len(macd_values) >= 9:
            signal_line = self._calculate_ema(macd_values, 9)
        else:
            signal_line = sum(macd_values) / len(macd_values) if macd_values else 0.0
        
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    def _calculate_bollinger_bands(
        self,
        prices: List[float]
    ) -> Tuple[float, float, float]:
        """حساب Bollinger Bands"""
        if len(prices) < 20:
            return 0.0, 0.0, 0.0
        
        window = prices[-20:]
        middle = sum(window) / 20
        
        # حساب الانحراف المعياري
        variance = sum((x - middle) ** 2 for x in window) / 20
        std_dev = variance ** 0.5
        
        upper = middle + (std_dev * 2)
        lower = middle - (std_dev * 2)
        
        return upper, middle, lower
    
    def _get_bb_position(
        self,
        price: float,
        upper: float,
        lower: float
    ) -> str:
        """تحديد موقع السعر بالنسبة لـ Bollinger Bands"""
        if upper == lower:
            return "MIDDLE"
        
        position = (price - lower) / (upper - lower)
        
        if position > 0.8:
            return "UPPER"
        elif position > 0.6:
            return "UPPER_MIDDLE"
        elif position > 0.4:
            return "MIDDLE"
        elif position > 0.2:
            return "LOWER_MIDDLE"
        else:
            return "LOWER"
    
    def _identify_support_resistance(
        self,
        highs: List[float],
        lows: List[float]
    ) -> Dict[str, List[float]]:
        """تحديد مستويات الدعم والمقاومة"""
        # خوارزمية مبسطة
        levels = {
            'resistance': [],
            'support': []
        }
        
        if len(highs) < 10 or len(lows) < 10:
            return levels
        
        # البحث عن قمم وقيعان محلية
        for i in range(2, len(highs) - 2):
            # مقاومة محلية
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and \
               highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                levels['resistance'].append(highs[i])
            
            # دعم محلي
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and \
               lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                levels['support'].append(lows[i])
        
        # تجميع المستويات القريبة
        tolerance = 0.005  # 0.5%
        levels['resistance'] = self._cluster_levels(levels['resistance'], tolerance)
        levels['support'] = self._cluster_levels(levels['support'], tolerance)
        
        return levels
    
    def _cluster_levels(self, levels: List[float], tolerance: float) -> List[float]:
        """تجمع المستويات القريبة من بعضها"""
        if not levels:
            return []
        
        levels.sort()
        clusters = []
        current_cluster = [levels[0]]
        
        for level in levels[1:]:
            if abs(level - current_cluster[-1]) / current_cluster[-1] <= tolerance:
                current_cluster.append(level)
            else:
                clusters.append(sum(current_cluster) / len(current_cluster))
                current_cluster = [level]
        
        if current_cluster:
            clusters.append(sum(current_cluster) / len(current_cluster))
        
        return clusters
    
    def _analyze_price_action(self, prices: List[float]) -> Dict[str, Any]:
        """تحليل حركة السعر"""
        if len(prices) < 3:
            return {'pattern': 'UNKNOWN', 'strength': 0.0}
        
        recent_prices = prices[-5:] if len(prices) >= 5 else prices
        
        # تحليل الأنماط البسيطة
        pattern = 'SIDEWAYS'
        strength = 0.0
        
        # Higher Highs / Higher Lows (صعودي)
        if len(recent_prices) >= 3:
            if all(recent_prices[i] > recent_prices[i-1] for i in range(1, len(recent_prices))):
                pattern = 'UPTREND'
                strength = 0.8
            elif all(recent_prices[i] < recent_prices[i-1] for i in range(1, len(recent_prices))):
                pattern = 'DOWNTREND'
                strength = 0.8
        
        # تحليل التذبذب
        price_range = max(recent_prices) - min(recent_prices)
        avg_price = sum(recent_prices) / len(recent_prices)
        volatility = price_range / avg_price if avg_price > 0 else 0
        
        return {
            'pattern': pattern,
            'strength': strength,
            'volatility': volatility,
            'range_pct': volatility * 100
        }
    
    def _determine_trend_direction(self, prices: List[float]) -> str:
        """تحديد اتجاه الترند"""
        if len(prices) < 20:
            return 'NEUTRAL'
        
        # استخدام Moving Averages
        sma_short = sum(prices[-10:]) / 10 if len(prices) >= 10 else prices[-1]
        sma_long = sum(prices[-20:]) / 20 if len(prices) >= 20 else prices[-1]
        
        current_price = prices[-1]
        
        if current_price > sma_short > sma_long:
            return 'STRONG_BULLISH'
        elif current_price > sma_short and sma_short > sma_long:
            return 'BULLISH'
        elif current_price < sma_short < sma_long:
            return 'STRONG_BEARISH'
        elif current_price < sma_short and sma_short < sma_long:
            return 'BEARISH'
        else:
            return 'NEUTRAL'
    
    def _calculate_momentum(self, prices: List[float]) -> float:
        """حساب الزخم"""
        if len(prices) < 10:
            return 0.0
        
        # نسبة التغير على آخر 10 فترات
        change = ((prices[-1] - prices[-10]) / prices[-10]) * 100 if prices[-10] > 0 else 0
        
        # تطبيع بين -1 و1
        normalized = max(-1.0, min(1.0, change / 10.0))
        
        return normalized
    
    # ====================== تحديد الإشارات ======================
    
    def _determine_timeframe_signal(
        self,
        indicators: Dict[str, Any]
    ) -> Tuple[str, float]:
        """
        تحديد الإشارة من المؤشرات
        """
        score = 50.0  # نقطة محايدة
        
        # وزن كل مؤشر
        weights = {
            'rsi': 0.20,
            'moving_averages': 0.25,
            'macd': 0.20,
            'bollinger': 0.15,
            'trend': 0.10,
            'momentum': 0.10
        }
        
        # تحليل RSI
        rsi = indicators.get('rsi')
        if rsi is not None:
            if rsi < 30:
                score += 20 * weights['rsi']
            elif rsi < 40:
                score += 10 * weights['rsi']
            elif rsi > 70:
                score -= 20 * weights['rsi']
            elif rsi > 60:
                score -= 10 * weights['rsi']
        
        # تحليل Moving Averages
        sma_20 = indicators.get('sma_20')
        sma_50 = indicators.get('sma_50')
        ema_12 = indicators.get('ema_12')
        ema_26 = indicators.get('ema_26')
        
        if all(v is not None for v in [sma_20, sma_50]):
            if sma_20 > sma_50:
                score += 15 * weights['moving_averages']
            else:
                score -= 15 * weights['moving_averages']
        
        if all(v is not None for v in [ema_12, ema_26]):
            if ema_12 > ema_26:
                score += 10 * weights['moving_averages']
            else:
                score -= 10 * weights['moving_averages']
        
        # تحليل MACD
        macd_info = indicators.get('macd')
        if macd_info:
            crossover = macd_info.get('crossover', False)
            histogram = macd_info.get('histogram', 0)
            
            if crossover and histogram > 0:
                score += 20 * weights['macd']
            elif not crossover and histogram < 0:
                score -= 20 * weights['macd']
            elif crossover:
                score += 10 * weights['macd']
            else:
                score -= 10 * weights['macd']
        
        # تحليل Bollinger Bands
        bb_info = indicators.get('bollinger')
        if bb_info:
            position = bb_info.get('position', 'MIDDLE')
            
            if position == 'LOWER':
                score += 15 * weights['bollinger']
            elif position == 'UPPER':
                score -= 15 * weights['bollinger']
            elif position == 'LOWER_MIDDLE':
                score += 7 * weights['bollinger']
            elif position == 'UPPER_MIDDLE':
                score -= 7 * weights['bollinger']
        
        # تحليل الترند
        trend = indicators.get('trend_direction', 'NEUTRAL')
        if trend == 'STRONG_BULLISH':
            score += 10 * weights['trend']
        elif trend == 'BULLISH':
            score += 5 * weights['trend']
        elif trend == 'STRONG_BEARISH':
            score -= 10 * weights['trend']
        elif trend == 'BEARISH':
            score -= 5 * weights['trend']
        
        # تحليل الزخم
        momentum = indicators.get('momentum', 0.0)
        score += momentum * 10 * weights['momentum']
        
        # تحديد الإشارة بناءً على النقاط
        score = max(0.0, min(100.0, score))
        
        if score >= 70:
            signal = 'BULLISH'
        elif score >= 60:
            signal = 'MILD_BULLISH'
        elif score <= 30:
            signal = 'BEARISH'
        elif score <= 40:
            signal = 'MILD_BEARISH'
        else:
            signal = 'NEUTRAL'
        
        return signal, score
    
    def _calculate_signal_confidence(
        self,
        indicators: Dict[str, Any],
        score: float
    ) -> float:
        """
        حساب ثقة الإشارة
        """
        confidence_factors = []
        
        # تناسق المؤشرات
        bullish_count = 0
        bearish_count = 0
        total_indicators = 0
        
        # RSI
        rsi = indicators.get('rsi')
        if rsi is not None:
            total_indicators += 1
            if rsi < 40:
                bullish_count += 1
            elif rsi > 60:
                bearish_count += 1
        
        # Moving Averages
        sma_20 = indicators.get('sma_20')
        sma_50 = indicators.get('sma_50')
        if sma_20 is not None and sma_50 is not None:
            total_indicators += 1
            if sma_20 > sma_50:
                bullish_count += 1
            else:
                bearish_count += 1
        
        # MACD
        macd_info = indicators.get('macd')
        if macd_info:
            crossover = macd_info.get('crossover', False)
            total_indicators += 1
            if crossover:
                bullish_count += 1
            else:
                bearish_count += 1
        
        # Bollinger Bands
        bb_info = indicators.get('bollinger')
        if bb_info:
            position = bb_info.get('position', 'MIDDLE')
            total_indicators += 1
            if position in ['LOWER', 'LOWER_MIDDLE']:
                bullish_count += 1
            elif position in ['UPPER', 'UPPER_MIDDLE']:
                bearish_count += 1
        
        # حساب تناسق المؤشرات
        if total_indicators > 0:
            if score >= 60:  # اتجاه صعودي
                consistency = bullish_count / total_indicators
            elif score <= 40:  # اتجاه هبوطي
                consistency = bearish_count / total_indicators
            else:
                consistency = 0.5
            
            confidence_factors.append(consistency)
        
        # قوة الترند
        trend_strength = self._calculate_trend_strength(indicators)
        confidence_factors.append(trend_strength)
        
        # وضوح الإشارة (مدى بعدها عن النقطة المحايدة)
        clarity = abs(score - 50) / 50
        confidence_factors.append(clarity)
        
        # حساب الثقة المتوسطة
        if confidence_factors:
            confidence = sum(confidence_factors) / len(confidence_factors)
        else:
            confidence = 0.5
        
        return min(1.0, max(0.0, confidence))
    
    def _calculate_trend_strength(self, indicators: Dict[str, Any]) -> float:
        """
        حساب قوة الترند
        """
        strength_factors = []
        
        # من حركة السعر
        price_action = indicators.get('price_action', {})
        pattern_strength = price_action.get('strength', 0.0)
        strength_factors.append(pattern_strength)
        
        # من اتجاه الترند
        trend = indicators.get('trend_direction', 'NEUTRAL')
        if trend == 'STRONG_BULLISH' or trend == 'STRONG_BEARISH':
            strength_factors.append(0.8)
        elif trend == 'BULLISH' or trend == 'BEARISH':
            strength_factors.append(0.5)
        else:
            strength_factors.append(0.2)
        
        # من الزخم
        momentum = abs(indicators.get('momentum', 0.0))
        strength_factors.append(momentum)
        
        if strength_factors:
            strength = sum(strength_factors) / len(strength_factors)
        else:
            strength = 0.3
        
        return min(1.0, max(0.0, strength))
    
    def _calculate_volatility(self, prices: List[float]) -> float:
        """
        حساب التقلب
        """
        if len(prices) < 10:
            return 0.0
        
        recent_prices = prices[-10:]
        returns = []
        
        for i in range(1, len(recent_prices)):
            if recent_prices[i-1] > 0:
                ret = (recent_prices[i] - recent_prices[i-1]) / recent_prices[i-1]
                returns.append(abs(ret))
        
        if not returns:
            return 0.0
        
        avg_return = sum(returns) / len(returns)
        
        # تطبيع بين 0 و1
        normalized = min(1.0, avg_return * 10)
        
        return normalized
    
    # ====================== حساب التقاء الإشارات ======================
    
    def _calculate_confluence(
        self,
        symbol: str,
        timeframe_signals: Dict[str, TimeframeSignal]
    ) -> ConfluenceAnalysis:
        """
        حساب التقاء الإشارات من الأطر الزمنية المختلفة
        """
        # حساب النقاط المرجحة
        weighted_scores = []
        weighted_confidences = []
        signal_directions = []
        
        for tf, signal in timeframe_signals.items():
            weight = self.TIMEFRAME_WEIGHTS.get(tf, 0.1)
            
            # تحويل الإشارة إلى نقاط
            direction_score = self._signal_to_score(signal.signal)
            
            weighted_score = direction_score * signal.confidence * weight
            weighted_scores.append(weighted_score)
            
            weighted_confidences.append(signal.confidence * weight)
            signal_directions.append(direction_score)
        
        # حساب النقاط الإجمالية
        if weighted_scores:
            total_weight = sum(self.TIMEFRAME_WEIGHTS.get(tf, 0.1) for tf in timeframe_signals.keys())
            overall_score = sum(weighted_scores) / total_weight if total_weight > 0 else 50.0
            overall_confidence = sum(weighted_confidences) / total_weight if total_weight > 0 else 0.5
        else:
            overall_score = 50.0
            overall_confidence = 0.5
        
        # تحديد الإشارة الإجمالية
        overall_signal = self._score_to_signal(overall_score)
        
        # حساب عوامل التقاء
        confluence_factors = self._calculate_confluence_factors(
            timeframe_signals, signal_directions
        )
        
        # تحديد مستوى المخاطرة
        risk_level = self._determine_risk_level(timeframe_signals, overall_confidence)
        
        # توليد التوصية
        recommendation, suggested_action = self._generate_recommendation(
            overall_signal, overall_confidence, risk_level
        )
        
        # حساب حجم المركز ونسب وقف الخسارة/جني الأرباح
        position_size, stop_loss, take_profit = self._calculate_trade_parameters(
            overall_signal, overall_confidence, risk_level, timeframe_signals
        )
        
        # إنشاء التحليل النهائي
        analysis = ConfluenceAnalysis(
            symbol=symbol,
            overall_score=overall_score,
            overall_signal=overall_signal,
            confidence=overall_confidence,
            timeframe_signals=timeframe_signals,
            confluence_factors=confluence_factors,
            recommendation=recommendation,
            risk_level=risk_level,
            suggested_action=suggested_action,
            position_size_pct=position_size,
            stop_loss_pct=stop_loss,
            take_profit_pct=take_profit
        )
        
        return analysis
    
    def _calculate_confluence_factors(
        self,
        timeframe_signals: Dict[str, TimeframeSignal],
        signal_directions: List[float]
    ) -> Dict[str, float]:
        """
        حساب عوامل التقاء الإشارات
        """
        factors = {}
        
        # تناسق الاتجاهات
        if signal_directions:
            avg_direction = sum(signal_directions) / len(signal_directions)
            direction_variance = sum((d - avg_direction) ** 2 for d in signal_directions) / len(signal_directions)
            
            # التناسق العالي عندما تكون التباين منخفض
            consistency = 1.0 - min(1.0, direction_variance * 2)
            factors['direction_consistency'] = consistency
        
        # تناسق الثقة
        confidences = [signal.confidence for signal in timeframe_signals.values()]
        if confidences:
            avg_confidence = sum(confidences) / len(confidences)
            factors['confidence_consistency'] = avg_confidence
        
        # تناسق قوة الترند
        trend_strengths = [signal.trend_strength for signal in timeframe_signals.values()]
        if trend_strengths:
            avg_trend_strength = sum(trend_strengths) / len(trend_strengths)
            factors['trend_strength_consistency'] = avg_trend_strength
        
        # تغطية الأطر الزمنية
        covered_timeframes = len(timeframe_signals)
        total_important_timeframes = len([tf for tf in self.TIMEFRAME_WEIGHTS if self.TIMEFRAME_WEIGHTS[tf] > 0.1])
        
        if total_important_timeframes > 0:
            coverage = covered_timeframes / total_important_timeframes
            factors['timeframe_coverage'] = coverage
        
        # مستوى التقاء عام
        if factors:
            confluence_level = sum(factors.values()) / len(factors)
            
            # تصنيف مستوى التقاء
            for level_name, level_threshold in self.CONFLUENCE_LEVELS.items():
                if confluence_level >= level_threshold:
                    factors['overall_confluence'] = level_name
                    factors['confluence_score'] = confluence_level
                    break
        
        return factors
    
    def _determine_risk_level(
        self,
        timeframe_signals: Dict[str, TimeframeSignal],
        overall_confidence: float
    ) -> str:
        """
        تحديد مستوى المخاطرة
        """
        # جمع عوامل المخاطرة
        risk_factors = []
        
        # الثقة العامة
        risk_factors.append(1.0 - overall_confidence)
        
        # التقلب
        volatilities = [signal.volatility for signal in timeframe_signals.values()]
        if volatilities:
            avg_volatility = sum(volatilities) / len(volatilities)
            risk_factors.append(avg_volatility)
        
        # تناقض الإشارات
        directions = [self._signal_to_score(signal.signal) for signal in timeframe_signals.values()]
        if directions:
            direction_std = self._calculate_std(directions)
            risk_factors.append(min(1.0, direction_std * 2))
        
        # حساب المخاطرة المتوسطة
        if risk_factors:
            risk_score = sum(risk_factors) / len(risk_factors)
        else:
            risk_score = 0.5
        
        # تصنيف مستوى المخاطرة
        if risk_score < 0.3:
            return "LOW"
        elif risk_score < 0.6:
            return "MEDIUM"
        else:
            return "HIGH"
    
    def _generate_recommendation(
        self,
        overall_signal: str,
        confidence: float,
        risk_level: str
    ) -> Tuple[str, str]:
        """
        توليد التوصية بناءً على الإشارة والثقة والمخاطرة
        """
        if confidence < 0.4:
            return "WAIT_FOR_CONFIRMATION", "HOLD"
        
        if overall_signal == "STRONG_BUY":
            if risk_level == "LOW":
                return "STRONG_BUY_SIGNAL", "ENTRY"
            elif risk_level == "MEDIUM":
                return "MODERATE_BUY_SIGNAL", "ENTRY"
            else:
                return "CAUTIOUS_BUY_SIGNAL", "PARTIAL_ENTRY"
        
        elif overall_signal == "BUY":
            if risk_level == "LOW":
                return "BUY_SIGNAL", "ENTRY"
            elif risk_level == "MEDIUM":
                return "MILD_BUY_SIGNAL", "PARTIAL_ENTRY"
            else:
                return "WEAK_BUY_SIGNAL", "HOLD"
        
        elif overall_signal == "STRONG_SELL":
            if risk_level == "LOW":
                return "STRONG_SELL_SIGNAL", "EXIT"
            elif risk_level == "MEDIUM":
                return "MODERATE_SELL_SIGNAL", "EXIT"
            else:
                return "CAUTIOUS_SELL_SIGNAL", "PARTIAL_EXIT"
        
        elif overall_signal == "SELL":
            if risk_level == "LOW":
                return "SELL_SIGNAL", "EXIT"
            elif risk_level == "MEDIUM":
                return "MILD_SELL_SIGNAL", "PARTIAL_EXIT"
            else:
                return "WEAK_SELL_SIGNAL", "HOLD"
        
        else:  # NEUTRAL
            return "NO_CLEAR_SIGNAL", "HOLD"
    
    def _calculate_trade_parameters(
        self,
        overall_signal: str,
        confidence: float,
        risk_level: str,
        timeframe_signals: Dict[str, TimeframeSignal]
    ) -> Tuple[float, float, float]:
        """
        حساب معاملات التداول المقترحة
        """
        # حجم المركز (نسبة من رأس المال)
        if overall_signal in ["STRONG_BUY", "STRONG_SELL"]:
            base_size = 0.05  # 5%
        elif overall_signal in ["BUY", "SELL"]:
            base_size = 0.03  # 3%
        else:
            base_size = 0.0
        
        # تعديل حسب الثقة
        size_multiplier = confidence
        position_size = base_size * size_multiplier
        
        # تعديل حسب المخاطرة
        if risk_level == "HIGH":
            position_size *= 0.5
        elif risk_level == "MEDIUM":
            position_size *= 0.75
        
        # حد أقصى وأدنى
        position_size = min(0.1, max(0.01, position_size))  # بين 1% و10%
        
        # وقف الخسارة
        if risk_level == "LOW":
            stop_loss = 1.0  # 1%
        elif risk_level == "MEDIUM":
            stop_loss = 1.5  # 1.5%
        else:
            stop_loss = 2.0  # 2%
        
        # جني الأرباح (نسبة إلى وقف الخسارة)
        risk_reward_ratio = 1.5  # نسبة المخاطرة إلى العائد
        take_profit = stop_loss * risk_reward_ratio
        
        # تعديل حسب التقلب
        volatilities = [signal.volatility for signal in timeframe_signals.values()]
        if volatilities:
            avg_volatility = sum(volatilities) / len(volatilities)
            # زيادة وقف الخسارة في الأسواق المتقلبة
            volatility_adjustment = 1.0 + (avg_volatility * 2)
            stop_loss *= volatility_adjustment
            take_profit *= volatility_adjustment
        
        return position_size, stop_loss, take_profit
    
    # ====================== دوال مساعدة ======================
    
    def _signal_to_score(self, signal: str) -> float:
        """
        تحويل الإشارة إلى نقاط رقمية
        """
        signal_map = {
            'BULLISH': 1.0,
            'MILD_BULLISH': 0.7,
            'NEUTRAL': 0.5,
            'MILD_BEARISH': 0.3,
            'BEARISH': 0.0
        }
        
        return signal_map.get(signal, 0.5)
    
    def _score_to_signal(self, score: float) -> str:
        """
        تحويل النقاط إلى إشارة
        """
        if score >= 80:
            return "STRONG_BUY"
        elif score >= 65:
            return "BUY"
        elif score >= 45:
            return "NEUTRAL"
        elif score >= 30:
            return "SELL"
        else:
            return "STRONG_SELL"
    
    def _calculate_std(self, values: List[float]) -> float:
        """
        حساب الانحراف المعياري
        """
        if len(values) < 2:
            return 0.0
        
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        
        return variance ** 0.5
    
    def _get_available_timeframes(self) -> List[str]:
        """
        الحصول على الأطر الزمنية المتاحة
        """
        # الأطر الزمنية المدعومة
        return ["15m", "1h", "4h", "1d"]
    
    def _is_cache_valid(self, analysis: ConfluenceAnalysis) -> bool:
        """
        التحقق من صلاحية كاش التحليل
        """
        # في النسخة المبسطة، نعتبر أن الكاش صالح دائمًا
        # يمكن التوسع لفحص الوقت في المستقبل
        return True
    
    def _is_signal_cache_valid(self, signal: TimeframeSignal) -> bool:
        """
        التحقق من صلاحية كاش الإشارة
        """
        # في النسخة المبسطة، نعتبر أن الكاش صالح دائمًا
        return True
    
    # ====================== واجهات عامة ======================
    
    def get_analysis_for_symbol(self, symbol: str) -> Optional[ConfluenceAnalysis]:
        """
        الحصول على تحليل التقاء لرمز معين
        """
        return self.analyze_confluence(symbol, use_cache=True)
    
    def get_timeframe_analysis(
        self,
        symbol: str,
        timeframe: str
    ) -> Optional[TimeframeSignal]:
        """
        الحصول على تحليل إطار زمني محدد
        """
        return self._analyze_timeframe(symbol, timeframe)
    
    def clear_cache(self, symbol: Optional[str] = None) -> None:
        """
        مسح الكاش
        """
        with self._cache_lock:
            if symbol:
                if symbol in self._analysis_cache:
                    del self._analysis_cache[symbol]
                # مسح إشارات هذا الرمز
                keys_to_remove = [k for k in self._signal_cache.keys() if k[0] == symbol]
                for key in keys_to_remove:
                    del self._signal_cache[key]
            else:
                self._analysis_cache.clear()
                self._signal_cache.clear()
        
        self.logger.info(f"Cache cleared for {symbol if symbol else 'all symbols'}")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        الحصول على إحصائيات الكاش
        """
        with self._cache_lock:
            analysis_count = len(self._analysis_cache)
            signal_count = len(self._signal_cache)
            
            symbols = list(self._analysis_cache.keys())
            
            cache_info = {
                'analysis_entries': analysis_count,
                'signal_entries': signal_count,
                'cached_symbols': symbols,
                'cache_size_mb': (analysis_count + signal_count) * 0.001  # تقدير
            }
        
        return cache_info
    
    def export_analysis(
        self,
        analysis: ConfluenceAnalysis,
        output_path: Optional[str] = None
    ) -> bool:
        """
        تصدير التحليل إلى ملف JSON
        """
        try:
            import json
            from datetime import datetime
            
            # تحويل التحليل إلى قاموس
            analysis_dict = {
                'symbol': analysis.symbol,
                'timestamp': datetime.now().isoformat(),
                'overall_score': analysis.overall_score,
                'overall_signal': analysis.overall_signal,
                'confidence': analysis.confidence,
                'recommendation': analysis.recommendation,
                'risk_level': analysis.risk_level,
                'suggested_action': analysis.suggested_action,
                'position_size_pct': analysis.position_size_pct,
                'stop_loss_pct': analysis.stop_loss_pct,
                'take_profit_pct': analysis.take_profit_pct,
                'confluence_factors': analysis.confluence_factors,
                'timeframe_signals': {}
            }
            
            # إضافة إشارات الأطر الزمنية
            for tf, signal in analysis.timeframe_signals.items():
                analysis_dict['timeframe_signals'][tf] = {
                    'score': signal.score,
                    'signal': signal.signal,
                    'confidence': signal.confidence,
                    'trend_strength': signal.trend_strength,
                    'volatility': signal.volatility,
                    'indicators_summary': {
                        k: str(v)[:100] for k, v in signal.indicators.items()
                    }
                }
            
            # تحديد مسار الحفظ
            if output_path is None:
                from pathlib import Path
                base_dir = Path(__file__).resolve().parent.parent
                output_dir = base_dir / "data" / "analysis"
                output_dir.mkdir(parents=True, exist_ok=True)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = str(output_dir / f"analysis_{analysis.symbol}_{timestamp}.json")
            
            # حفظ الملف
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(analysis_dict, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"Analysis exported to {output_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to export analysis: {e}")
            return False