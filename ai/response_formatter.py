from model import AIIntentType
from typing import Any, Dict

class ResponseFormatter:
    """Formats AI responses for better user experience"""
    
    def format(self, response: dict, intent: AIIntentType) -> dict:
        """Format response based on intent type"""
        
        formatters = {
            AIIntentType.SEARCH_EVENTS: self._format_events,
            AIIntentType.ANALYZE_SALES: self._format_sales,
            AIIntentType.INVENTORY_CHECK: self._format_inventory,
            AIIntentType.PRICING_RECOMMENDATION: self._format_pricing,
        }
        
        formatter = formatters.get(intent, self._format_default)
        return formatter(response)
    
    def _format_default(self, response: dict) -> dict:
        """Default formatting"""
        return {
            "message": response.get("message", ""),
            "metadata": response.get("data")
        }
    
    def _format_events(self, response: dict) -> dict:
        """Format event search results"""
        message = response.get("message", "")
        data = response.get("data", {})
        events = data.get("events", [])
        
        if events:
            # Create a nicely formatted list
            event_list = []
            for i, event in enumerate(events, 1):
                event_list.append(
                    f"{i}. **{event['name']}**\n"
                    f"   📅 {event['date']}\n"
                    f"   📍 {event['location']}, {event.get('city', '')}"
                )
            
            formatted_message = f"{message}\n\n" + "\n\n".join(event_list)
        else:
            formatted_message = message
        
        return {
            "message": formatted_message,
            "metadata": {
                "event_count": len(events),
                "events": events
            }
        }
    
    def _format_sales(self, response: dict) -> dict:
        """Format sales analytics"""
        message = response.get("message", "")
        data = response.get("data", {})
        
        if data:
            formatted_message = (
                f"📊 **{message}**\n\n"
                f"💰 Total Revenue: **KSh {data.get('total_revenue', 0):,.2f}**\n"
                f"🎟️ Tickets Sold: **{data.get('total_tickets', 0)}**\n"
                f"📈 Average per Transaction: **KSh {data.get('average_transaction', 0):,.2f}**\n"
                f"📅 Period: {data.get('period', 'N/A')}"
            )
        else:
            formatted_message = message
        
        return {
            "message": formatted_message,
            "metadata": data
        }
    
    def _format_inventory(self, response: dict) -> dict:
        """Format inventory check results"""
        message = response.get("message", "")
        data = response.get("data", {})
        low_inventory = data.get("low_inventory", [])
        
        if low_inventory:
            items = []
            for item in low_inventory:
                items.append(
                    f"• {item['event']} - {item['ticket_type']}: "
                    f"**{item['remaining']} tickets left**"
                )
            
            formatted_message = f"{message}\n\n" + "\n".join(items)
        else:
            formatted_message = message
        
        return {
            "message": formatted_message,
            "metadata": {"low_inventory_count": len(low_inventory)}
        }
    
    def _format_pricing(self, response: dict) -> dict:
        """Format pricing recommendations"""
        message = response.get("message", "")
        data = response.get("data", {})
        recommendations = data.get("recommendations", [])
        
        if recommendations:
            items = []
            for rec in recommendations:
                change = rec.get('price_change_percentage', 0)
                arrow = "📈" if change > 0 else "📉"
                items.append(
                    f"{arrow} {rec.get('ticket_type_name', 'Ticket')}: "
                    f"KSh {rec.get('current_price', 0)} → "
                    f"KSh {rec.get('recommended_price', 0)} "
                    f"({change:+.1f}%)"
                )
            
            formatted_message = f"{message}\n\n" + "\n".join(items)
        else:
            formatted_message = message
        
        return {
            "message": formatted_message,
            "metadata": {"recommendation_count": len(recommendations)}
        }
    
    def format_error(self, error_message: str) -> dict:
        """Format error messages consistently"""
        return {
            "message": f"❌ {error_message}",
            "metadata": {"is_error": True}
        }
    
    def format_confirmation_request(self, action_description: str, params: dict) -> dict:
        """Format action confirmation requests"""
        param_list = []
        for key, value in params.items():
            if value:
                param_list.append(f"• {key.replace('_', ' ').title()}: {value}")
        
        message = (
            f"I'm ready to {action_description}:\n\n"
            + "\n".join(param_list) +
            "\n\n✅ Should I proceed with this action?"
        )
        
        return {
            "message": message,
            "metadata": {
                "requires_confirmation": True,
                "params": params
            }
        }