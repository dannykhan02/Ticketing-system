from model import AIIntentType
import re
from datetime import datetime, timedelta

class IntentClassifier:
    """Classifies user queries into actionable intents"""
    
    def __init__(self):
        self.patterns = {
            AIIntentType.SEARCH_EVENTS: [
                r'\b(find|search|show|list|get|display|view)\b.*\b(event|concert|show|happening)\b',
                r'\bevents?\b.*\b(in|at|near|around)\b',
                r'\bwhat.*(event|happening|going on)\b',
                r'\bupcoming\b.*\bevent',
            ],
            AIIntentType.CREATE_EVENT: [
                r'\b(create|make|add|new|organize|setup|start)\b.*\bevent\b',
                r'\borganize\b.*\b(concert|show|party|gathering)\b',
                r'\bschedule\b.*\bevent\b',
            ],
            AIIntentType.UPDATE_EVENT: [
                r'\b(update|edit|modify|change)\b.*\bevent\b',
                r'\bchange\b.*\b(date|time|location|venue)\b',
                r'\bevent\b.*\b(update|modification)\b',
            ],
            AIIntentType.DELETE_EVENT: [
                r'\b(delete|remove|cancel)\b.*\bevent\b',
                r'\bcancel\b.*\b(concert|show)\b',
            ],
            AIIntentType.CREATE_TICKETS: [
                r'\b(create|add|setup|new)\b.*\b(ticket|tickets)\b',
                r'\b(ticket type|ticket category)\b',
            ],
            AIIntentType.UPDATE_TICKETS: [
                r'\b(update|edit|change|modify)\b.*\b(ticket|price|pricing)\b',
                r'\bchange\b.*\b(ticket.*price|pricing)\b',
            ],
            AIIntentType.ANALYZE_SALES: [
                r'\b(sales|revenue|earnings|income)\b',
                r'\bhow (much|many).*\b(sold|made|earned|revenue)\b',
                r'\b(analyze|analysis|report|summary).*\bsales\b',
                r'\bshow.*\b(sales|revenue|earnings)\b',
            ],
            AIIntentType.GENERATE_REPORT: [
                r'\b(generate|create|make|prepare)\b.*\breport\b',
                r'\breport\b.*\b(on|for|about)\b',
                r'\bsummary\b.*\b(of|for)\b',
            ],
            AIIntentType.MANAGE_PARTNERS: [
                r'\b(partner|collaboration|sponsor|collaborator)\b',
                r'\b(add|create|remove|manage)\b.*\bpartner\b',
            ],
            AIIntentType.PRICING_RECOMMENDATION: [
                r'\b(pricing|price)\b.*\b(recommendation|suggestion|advice)\b',
                r'\bwhat.*\bprice\b',
                r'\bhow much.*\bcharge\b',
                r'\boptimal.*\bprice\b',
            ],
            AIIntentType.INVENTORY_CHECK: [
                r'\b(inventory|stock|remaining|left)\b.*\bticket',
                r'\bhow many.*\b(left|remaining|available)\b',
                r'\bticket.*\b(availability|inventory|stock)\b',
            ],
            AIIntentType.REVENUE_ANALYSIS: [
                r'\brevenue\b.*\b(analysis|breakdown|summary)\b',
                r'\bprofit\b.*\b(analysis|report)\b',
            ],
        }
    
    def classify(self, query: str) -> tuple:
        """
        Returns (intent, confidence, extracted_params)
        """
        query_lower = query.lower()
        
        # Check patterns
        for intent, patterns in self.patterns.items():
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    params = self.extract_parameters(query, intent)
                    return (intent, 0.85, params)
        
        # Default to general query
        return (AIIntentType.GENERAL_QUERY, 0.5, {})
    
    def extract_parameters(self, query: str, intent: AIIntentType) -> dict:
        """Extract relevant parameters based on intent"""
        params = {}
        query_lower = query.lower()
        
        if intent == AIIntentType.CREATE_EVENT:
            params = self._extract_event_params(query)
        
        elif intent == AIIntentType.UPDATE_EVENT:
            params = self._extract_update_params(query)
        
        elif intent == AIIntentType.SEARCH_EVENTS:
            params = self._extract_search_params(query)
        
        elif intent == AIIntentType.ANALYZE_SALES:
            params = self._extract_timeframe_params(query)
        
        elif intent == AIIntentType.CREATE_TICKETS:
            params = self._extract_ticket_params(query)
        
        return params
    
    def _extract_event_params(self, query: str) -> dict:
        """Extract event creation parameters"""
        params = {}
        
        # Extract event name (first quoted text or after "called/named")
        name_match = re.search(r'["\']([^"\']+)["\']', query)
        if name_match:
            params['name'] = name_match.group(1)
        else:
            # Try "called X" or "named X"
            name_match = re.search(r'\b(called|named)\s+([A-Z][a-zA-Z\s]+)', query)
            if name_match:
                params['name'] = name_match.group(2).strip()
        
        # Extract city
        cities = ['nairobi', 'mombasa', 'kisumu', 'nakuru', 'eldoret', 'thika', 'juja']
        for city in cities:
            if city in query.lower():
                params['city'] = city.capitalize()
                break
        
        # Extract date
        params.update(self._extract_date(query))
        
        # Extract location/venue
        location_match = re.search(r'\bat\s+([A-Z][a-zA-Z\s]+(?:Stadium|Center|Hall|Arena))', query)
        if location_match:
            params['location'] = location_match.group(1).strip()
        
        return params
    
    def _extract_update_params(self, query: str) -> dict:
        """Extract update parameters"""
        params = {}
        
        # Extract event ID
        id_match = re.search(r'\bevent\s+(?:id\s+)?(\d+)', query.lower())
        if id_match:
            params['event_id'] = int(id_match.group(1))
        
        # Extract what to update
        if 'date' in query.lower():
            params.update(self._extract_date(query))
        
        if 'location' in query.lower() or 'venue' in query.lower():
            location_match = re.search(r'(?:location|venue)\s+(?:to\s+)?["\']?([^"\']+)["\']?', query, re.IGNORECASE)
            if location_match:
                params['location'] = location_match.group(1).strip()
        
        if 'name' in query.lower():
            name_match = re.search(r'name\s+(?:to\s+)?["\']([^"\']+)["\']', query, re.IGNORECASE)
            if name_match:
                params['name'] = name_match.group(1)
        
        return params
    
    def _extract_search_params(self, query: str) -> dict:
        """Extract search parameters"""
        params = {}
        
        # Extract city
        cities = ['nairobi', 'mombasa', 'kisumu', 'nakuru', 'eldoret']
        for city in cities:
            if city in query.lower():
                params['city'] = city.capitalize()
                break
        
        # Extract category
        categories = ['concert', 'conference', 'workshop', 'sports', 'festival', 'party']
        for category in categories:
            if category in query.lower():
                params['category'] = category.capitalize()
                break
        
        # Extract time period
        if 'today' in query.lower():
            params['time_filter'] = 'today'
        elif 'upcoming' in query.lower() or 'future' in query.lower():
            params['time_filter'] = 'upcoming'
        elif 'past' in query.lower():
            params['time_filter'] = 'past'
        
        return params
    
    def _extract_timeframe_params(self, query: str) -> dict:
        """Extract time period for analytics"""
        params = {'days': 30}  # default
        
        # Check for specific time periods
        if 'today' in query.lower():
            params['days'] = 1
        elif 'week' in query.lower():
            params['days'] = 7
        elif 'month' in query.lower():
            params['days'] = 30
        elif 'quarter' in query.lower():
            params['days'] = 90
        elif 'year' in query.lower():
            params['days'] = 365
        
        # Check for "last X days"
        days_match = re.search(r'last\s+(\d+)\s+days?', query.lower())
        if days_match:
            params['days'] = int(days_match.group(1))
        
        return params
    
    def _extract_ticket_params(self, query: str) -> dict:
        """Extract ticket type parameters"""
        params = {}
        
        # Extract ticket type
        ticket_types = ['regular', 'vip', 'vvip', 'student', 'early_bird', 'couples', 'group']
        for ticket_type in ticket_types:
            if ticket_type in query.lower():
                params['type_name'] = ticket_type.upper()
                break
        
        # Extract price
        price_match = re.search(r'(?:ksh|kes|sh)?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', query.lower())
        if price_match:
            price_str = price_match.group(1).replace(',', '')
            params['price'] = float(price_str)
        
        # Extract quantity
        quantity_match = re.search(r'(\d+)\s+tickets?', query.lower())
        if quantity_match:
            params['quantity'] = int(quantity_match.group(1))
        
        return params
    
    def _extract_date(self, query: str) -> dict:
        """Extract date from query"""
        params = {}
        today = datetime.now().date()
        
        # Relative dates
        if 'today' in query.lower():
            params['date'] = today.isoformat()
        elif 'tomorrow' in query.lower():
            params['date'] = (today + timedelta(days=1)).isoformat()
        elif 'next week' in query.lower():
            params['date'] = (today + timedelta(days=7)).isoformat()
        
        # Specific dates
        date_patterns = [
            r'(\d{4})-(\d{2})-(\d{2})',  # YYYY-MM-DD
            r'(\d{1,2})/(\d{1,2})/(\d{4})',  # MM/DD/YYYY or DD/MM/YYYY
            r'(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{4})',  # DD Month YYYY
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, query.lower())
            if match:
                try:
                    if pattern == date_patterns[0]:  # YYYY-MM-DD
                        params['date'] = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
                    elif pattern == date_patterns[2]:  # DD Month YYYY
                        month_map = {
                            'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
                            'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
                            'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'
                        }
                        day = match.group(1).zfill(2)
                        month = month_map[match.group(2)[:3]]
                        year = match.group(3)
                        params['date'] = f"{year}-{month}-{day}"
                except:
                    pass
                break
        
        return params