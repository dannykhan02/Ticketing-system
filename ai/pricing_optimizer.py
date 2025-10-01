"""
AI-Powered Pricing Optimizer for Ticketing System
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional
from sqlalchemy import func

from model import (
    db, Event, TicketType, Ticket, Transaction, Category, Currency,
    PaymentStatus, TicketTypeEnum, AIPricingRecommendation,
    AITicketAnalysis, AIInsight, AIManager
)


class PricingOptimizer:
    """AI-powered pricing optimization engine"""

    def __init__(self):
        self.confidence_threshold = 0.7
        self.price_change_limit = 0.30
        self.market_data_days = 90

    def generate_pricing_recommendation(
        self,
        ticket_type_id: int,
        event_id: int,
        current_price: Decimal,
        currency_id: int
    ) -> Dict:
        """Generate comprehensive pricing recommendation for a ticket type"""
        try:
            ticket_type = TicketType.query.get(ticket_type_id)
            event = Event.query.get(event_id)
            
            if not ticket_type or not event:
                return {"error": "Ticket type or event not found"}

            factors = self._analyze_pricing_factors(ticket_type, event, current_price)
            recommended_price = self._calculate_optimal_price(current_price, factors)
            recommended_price = self._apply_price_limits(current_price, recommended_price)
            confidence = self._calculate_confidence(factors)
            reasoning = self._generate_reasoning(factors, current_price, recommended_price)
            revenue_projections = self._project_revenue(ticket_type, current_price, recommended_price, factors)
            
            recommendation = AIPricingRecommendation(
                ticket_type_id=ticket_type_id,
                event_id=event_id,
                current_price=current_price,
                currency_id=currency_id,
                recommended_price=recommended_price,
                price_change_percentage=float(((recommended_price - current_price) / current_price) * 100),
                recommendation_reason=reasoning,
                factors_considered=factors,
                expected_revenue_current=revenue_projections['current'],
                expected_revenue_recommended=revenue_projections['recommended'],
                confidence_level=confidence,
                expires_at=datetime.utcnow() + timedelta(days=7)
            )
            
            db.session.add(recommendation)
            db.session.commit()
            
            return {
                "success": True,
                "recommendation_id": recommendation.id,
                "current_price": float(current_price),
                "recommended_price": float(recommended_price),
                "price_change_percentage": recommendation.price_change_percentage,
                "confidence_level": confidence,
                "reasoning": reasoning,
                "factors": factors,
                "revenue_projections": revenue_projections
            }
            
        except Exception as e:
            db.session.rollback()
            return {"error": f"Pricing optimization failed: {str(e)}"}

    def _analyze_pricing_factors(self, ticket_type: TicketType, event: Event, current_price: Decimal) -> Dict:
        """Analyze various factors affecting pricing"""
        return {
            "market_average": self._get_market_average_price(ticket_type, event),
            "historical_performance": self._analyze_historical_performance(ticket_type),
            "demand_indicators": self._analyze_demand_indicators(event),
            "time_factors": self._analyze_time_factors(event),
            "competition": self._analyze_competition(event),
            "inventory_status": self._analyze_inventory_status(ticket_type),
            "sales_velocity": self._calculate_sales_velocity(ticket_type),
            "event_characteristics": self._analyze_event_characteristics(event)
        }

    def _get_market_average_price(self, ticket_type: TicketType, event: Event) -> Optional[float]:
        """Get average price for similar tickets in the market"""
        similar_events = Event.query.filter(
            Event.category_id == event.category_id,
            Event.city == event.city,
            Event.date >= datetime.utcnow().date() - timedelta(days=self.market_data_days),
            Event.id != event.id
        ).limit(20).all()
        
        if not similar_events:
            return None
        
        similar_ticket_ids = [
            tt.id for e in similar_events 
            for tt in e.ticket_types 
            if tt.type_name == ticket_type.type_name
        ]
        
        if not similar_ticket_ids:
            return None
        
        avg_price = db.session.query(func.avg(TicketType.price)).filter(
            TicketType.id.in_(similar_ticket_ids)
        ).scalar()
        
        return float(avg_price) if avg_price else None

    def _analyze_historical_performance(self, ticket_type: TicketType) -> Dict:
        """Analyze historical sales performance"""
        tickets_sold = Ticket.query.filter(
            Ticket.ticket_type_id == ticket_type.id,
            Ticket.payment_status.in_([PaymentStatus.COMPLETED, PaymentStatus.PAID])
        ).count()
        
        sell_through_rate = (tickets_sold / ticket_type.quantity) if ticket_type.quantity > 0 else 0
        
        sales_by_day = db.session.query(
            func.date(Ticket.purchase_date).label('date'),
            func.count(Ticket.id).label('count')
        ).filter(
            Ticket.ticket_type_id == ticket_type.id,
            Ticket.payment_status.in_([PaymentStatus.COMPLETED, PaymentStatus.PAID])
        ).group_by(func.date(Ticket.purchase_date)).all()
        
        return {
            "tickets_sold": tickets_sold,
            "tickets_remaining": ticket_type.quantity - tickets_sold,
            "sell_through_rate": sell_through_rate,
            "sales_timeline": [{"date": str(s.date), "count": s.count} for s in sales_by_day]
        }

    def _analyze_demand_indicators(self, event: Event) -> Dict:
        """Analyze demand signals for the event"""
        likes_count = event.likes.count()
        
        category_events_avg = db.session.query(
            func.avg(
                db.select([func.count()])
                .select_from(Ticket)
                .where(Ticket.event_id == Event.id)
                .correlate(Event)
                .scalar_subquery()
            )
        ).filter(Event.category_id == event.category_id).scalar()
        
        return {
            "likes_count": likes_count,
            "category_average_sales": float(category_events_avg) if category_events_avg else 0,
            "is_featured": event.featured
        }

    def _analyze_time_factors(self, event: Event) -> Dict:
        """Analyze time-based factors"""
        days_until_event = (event.date - datetime.utcnow().date()).days
        
        if days_until_event > 60:
            pricing_phase = "early_bird"
            phase_multiplier = 0.85
        elif days_until_event > 30:
            pricing_phase = "regular"
            phase_multiplier = 1.0
        elif days_until_event > 7:
            pricing_phase = "last_chance"
            phase_multiplier = 1.1
        else:
            pricing_phase = "final_days"
            phase_multiplier = 1.15
        
        return {
            "days_until_event": days_until_event,
            "pricing_phase": pricing_phase,
            "phase_multiplier": phase_multiplier,
            "is_weekend": event.date.weekday() in [5, 6]
        }

    def _analyze_competition(self, event: Event) -> Dict:
        """Analyze competing events"""
        competing_events = Event.query.filter(
            Event.city == event.city,
            Event.date.between(
                event.date - timedelta(days=7),
                event.date + timedelta(days=7)
            ),
            Event.id != event.id
        ).count()
        
        return {
            "competing_events_count": competing_events,
            "competition_level": "high" if competing_events > 3 else "medium" if competing_events > 0 else "low"
        }

    def _analyze_inventory_status(self, ticket_type: TicketType) -> Dict:
        """Analyze inventory levels"""
        tickets_sold = Ticket.query.filter(
            Ticket.ticket_type_id == ticket_type.id,
            Ticket.payment_status.in_([PaymentStatus.COMPLETED, PaymentStatus.PAID])
        ).count()
        
        remaining = ticket_type.quantity - tickets_sold
        inventory_percentage = (remaining / ticket_type.quantity) * 100 if ticket_type.quantity > 0 else 0
        
        if inventory_percentage < 20:
            status = "low"
            urgency_multiplier = 1.2
        elif inventory_percentage < 50:
            status = "medium"
            urgency_multiplier = 1.05
        else:
            status = "high"
            urgency_multiplier = 0.95
        
        return {
            "remaining_tickets": remaining,
            "inventory_percentage": inventory_percentage,
            "status": status,
            "urgency_multiplier": urgency_multiplier
        }

    def _calculate_sales_velocity(self, ticket_type: TicketType) -> Dict:
        """Calculate how fast tickets are selling"""
        week_ago = datetime.utcnow() - timedelta(days=7)
        recent_sales = Ticket.query.filter(
            Ticket.ticket_type_id == ticket_type.id,
            Ticket.purchase_date >= week_ago,
            Ticket.payment_status.in_([PaymentStatus.COMPLETED, PaymentStatus.PAID])
        ).count()
        
        velocity = recent_sales / 7.0
        
        total_sold = Ticket.query.filter(
            Ticket.ticket_type_id == ticket_type.id,
            Ticket.payment_status.in_([PaymentStatus.COMPLETED, PaymentStatus.PAID])
        ).count()
        
        first_sale = Ticket.query.filter(
            Ticket.ticket_type_id == ticket_type.id,
            Ticket.payment_status.in_([PaymentStatus.COMPLETED, PaymentStatus.PAID])
        ).order_by(Ticket.purchase_date.asc()).first()
        
        if first_sale:
            days_selling = (datetime.utcnow() - first_sale.purchase_date).days or 1
            avg_velocity = total_sold / days_selling
        else:
            avg_velocity = 0
        
        return {
            "recent_velocity": velocity,
            "average_velocity": avg_velocity,
            "trend": "accelerating" if velocity > avg_velocity else "decelerating"
        }

    def _analyze_event_characteristics(self, event: Event) -> Dict:
        """Analyze event-specific characteristics"""
        return {
            "has_amenities": len(event.amenities or []) > 0,
            "amenities_count": len(event.amenities or []),
            "is_featured": event.featured,
            "has_collaborations": len(event.collaborations) > 0,
            "category": event.event_category.name if event.event_category else None
        }

    def _calculate_optimal_price(self, current_price: Decimal, factors: Dict) -> Decimal:
        """Calculate optimal price based on all factors"""
        base_price = float(current_price)
        total_multiplier = 1.0
        
        if factors['market_average']:
            market_avg = factors['market_average']
            if market_avg > base_price * 1.1:
                total_multiplier *= 1.08
            elif market_avg < base_price * 0.9:
                total_multiplier *= 0.95
        
        total_multiplier *= factors['time_factors']['phase_multiplier']
        total_multiplier *= factors['inventory_status']['urgency_multiplier']
        
        if factors['sales_velocity']['trend'] == 'accelerating':
            total_multiplier *= 1.05
        
        if factors['competition']['competition_level'] == 'high':
            total_multiplier *= 0.97
        elif factors['competition']['competition_level'] == 'low':
            total_multiplier *= 1.03
        
        if factors['event_characteristics']['is_featured']:
            total_multiplier *= 1.05
        
        optimal_price = Decimal(str(base_price * total_multiplier))
        return self._round_price(optimal_price)

    def _round_price(self, price: Decimal) -> Decimal:
        """Round price to psychological pricing points"""
        price_float = float(price)
        
        if price_float < 10:
            return Decimal(str(round(price_float * 2) / 2))
        elif price_float < 100:
            base = int(price_float)
            if price_float - base > 0.5:
                return Decimal(str(base + 0.99))
            else:
                return Decimal(str(base + 0.50))
        else:
            return Decimal(str(round(price_float / 5) * 5))

    def _apply_price_limits(self, current_price: Decimal, recommended_price: Decimal) -> Decimal:
        """Ensure price changes don't exceed limits"""
        max_increase = current_price * Decimal(str(1 + self.price_change_limit))
        max_decrease = current_price * Decimal(str(1 - self.price_change_limit))
        
        if recommended_price > max_increase:
            return max_increase
        elif recommended_price < max_decrease:
            return max_decrease
        
        return recommended_price

    def _calculate_confidence(self, factors: Dict) -> float:
        """Calculate confidence level in recommendation"""
        confidence_factors = []
        
        if factors['market_average']:
            confidence_factors.append(0.9)
        
        hist = factors['historical_performance']
        if hist['tickets_sold'] > 10:
            confidence_factors.append(0.85)
        elif hist['tickets_sold'] > 0:
            confidence_factors.append(0.6)
        
        if factors['sales_velocity']['recent_velocity'] > 0:
            confidence_factors.append(0.8)
        
        days_until = factors['time_factors']['days_until_event']
        if days_until > 30:
            confidence_factors.append(0.9)
        elif days_until > 7:
            confidence_factors.append(0.75)
        else:
            confidence_factors.append(0.6)
        
        return sum(confidence_factors) / len(confidence_factors) if confidence_factors else 0.5

    def _generate_reasoning(self, factors: Dict, current_price: Decimal, recommended_price: Decimal) -> str:
        """Generate human-readable reasoning for the recommendation"""
        price_change = ((recommended_price - current_price) / current_price) * 100
        direction = "increase" if price_change > 0 else "decrease"
        
        reasons = []
        
        if factors['market_average']:
            market_avg = factors['market_average']
            if abs(float(current_price) - market_avg) / market_avg > 0.1:
                reasons.append(f"Market analysis shows similar tickets averaging ${market_avg:.2f}")
        
        inventory = factors['inventory_status']
        if inventory['status'] == 'low':
            reasons.append(f"Low inventory ({inventory['remaining_tickets']} tickets remaining) suggests strong demand")
        elif inventory['status'] == 'high':
            reasons.append("High inventory levels suggest room for promotional pricing")
        
        time_factors = factors['time_factors']
        if time_factors['pricing_phase'] == 'early_bird':
            reasons.append("Early bird pricing recommended to drive initial sales")
        elif time_factors['pricing_phase'] in ['last_chance', 'final_days']:
            reasons.append("Last-minute pricing premium based on urgency")
        
        reasoning_text = f"Recommended {direction} of {abs(price_change):.1f}% (${float(current_price):.2f} → ${float(recommended_price):.2f}). "
        
        if reasons:
            reasoning_text += "Key factors: " + "; ".join(reasons) + "."
        
        return reasoning_text

    def _project_revenue(self, ticket_type: TicketType, current_price: Decimal, recommended_price: Decimal, factors: Dict) -> Dict:
        """Project revenue under current and recommended pricing"""
        tickets_sold = Ticket.query.filter(
            Ticket.ticket_type_id == ticket_type.id,
            Ticket.payment_status.in_([PaymentStatus.COMPLETED, PaymentStatus.PAID])
        ).count()
        
        remaining = ticket_type.quantity - tickets_sold
        velocity = factors['sales_velocity']['average_velocity']
        days_until = factors['time_factors']['days_until_event']
        
        estimated_sales = min(remaining, int(velocity * days_until))
        
        price_change_pct = ((recommended_price - current_price) / current_price)
        elasticity = -0.5
        demand_adjustment = 1 + (float(price_change_pct) * elasticity)
        
        adjusted_sales = int(estimated_sales * demand_adjustment)
        adjusted_sales = max(0, min(remaining, adjusted_sales))
        
        return {
            "current": float(current_price * estimated_sales),
            "recommended": float(recommended_price * adjusted_sales),
            "estimated_sales_current": estimated_sales,
            "estimated_sales_recommended": adjusted_sales
        }

    def bulk_optimize_event_pricing(self, event_id: int) -> Dict:
        """Optimize pricing for all ticket types in an event"""
        event = Event.query.get(event_id)
        if not event:
            return {"error": "Event not found"}
        
        results = []
        for ticket_type in event.ticket_types:
            result = self.generate_pricing_recommendation(
                ticket_type_id=ticket_type.id,
                event_id=event_id,
                current_price=ticket_type.price,
                currency_id=ticket_type.currency_id or 1
            )
            results.append({"ticket_type": ticket_type.type_name.value, "result": result})
        
        return {"event_id": event_id, "event_name": event.name, "recommendations": results}

    def apply_pricing_recommendation(self, recommendation_id: int) -> Dict:
        """Apply a pricing recommendation to a ticket type"""
        recommendation = AIPricingRecommendation.query.get(recommendation_id)
        if not recommendation:
            return {"error": "Recommendation not found"}
        
        if recommendation.is_applied:
            return {"error": "Recommendation already applied"}
        
        ticket_type = TicketType.query.get(recommendation.ticket_type_id)
        if not ticket_type:
            return {"error": "Ticket type not found"}
        
        old_price = ticket_type.price
        ticket_type.price = recommendation.recommended_price
        ticket_type.ai_suggested_price = recommendation.recommended_price
        ticket_type.ai_price_confidence = recommendation.confidence_level
        
        recommendation.is_applied = True
        recommendation.applied_at = datetime.utcnow()
        
        db.session.commit()
        
        AIManager.create_insight(
            organizer_id=ticket_type.event.organizer_id,
            event_id=ticket_type.event_id,
            insight_type="pricing_applied",
            title=f"Pricing Updated: {ticket_type.type_name.value}",
            description=f"Price changed from ${float(old_price):.2f} to ${float(recommendation.recommended_price):.2f}. {recommendation.recommendation_reason}",
            priority="medium",
            confidence_score=recommendation.confidence_level
        )
        
        return {
            "success": True,
            "ticket_type_id": ticket_type.id,
            "old_price": float(old_price),
            "new_price": float(recommendation.recommended_price),
            "message": "Pricing recommendation applied successfully"
        }


# Singleton instance
pricing_optimizer = PricingOptimizer()