from flask import jsonify, request, current_app
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from model import db, User, Event, TicketType, Organizer, UserRole, PaymentStatus, Transaction, Ticket
import psutil
import logging
import hashlib
import time
from datetime import datetime, timedelta
from sqlalchemy import func, text
from functools import wraps
from config import Config
import calendar
import redis


# Configure logging with security events
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security')

# Initialize rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100 per hour"],
    storage_uri=Config.REDIS_URL if hasattr(Config, 'REDIS_URL') else "memory://"
)

# Security configuration
SECURITY_CONFIG = {
    'MAX_FAILED_ATTEMPTS': 5,
    'LOCKOUT_DURATION': 300,  # 5 minutes
    'SESSION_TIMEOUT': 3600,  # 1 hour
    'AUDIT_LOG_RETENTION': 90,  # 90 days
    'ALLOWED_USER_AGENTS': [],  # Whitelist if needed
    'BLOCKED_IPS': set(),
    'REQUIRE_2FA_FOR_ADMIN': True
}

def security_audit_log(user_id, action, ip_address, user_agent, additional_data=None):
    """Log security events for audit trail."""
    try:
        security_logger.info(
            f"USER_ID:{user_id} | ACTION:{action} | IP:{ip_address} | "
            f"UA:{user_agent[:100]} | DATA:{additional_data or 'None'}"
        )
    except Exception as e:
        logger.error(f"Failed to log security event: {e}")

def validate_user_session(f):
    """Enhanced JWT validation with session checks."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            verify_jwt_in_request()
            identity = get_jwt_identity()
            
            # Check if user exists and is active
            user = User.query.get(identity)
            if not user:
                security_audit_log(
                    identity, 'INVALID_USER_ACCESS_ATTEMPT', 
                    get_remote_address(), request.headers.get('User-Agent', '')
                )
                return {"error": "Invalid user"}, 401
            
            # Check if user account is still active
            if hasattr(user, 'is_active') and not user.is_active:
                security_audit_log(
                    user.id, 'DISABLED_USER_ACCESS_ATTEMPT', 
                    get_remote_address(), request.headers.get('User-Agent', '')
                )
                return {"error": "Account disabled"}, 403
            
            # Check for suspicious activity
            if _is_suspicious_activity(user.id, get_remote_address()):
                security_audit_log(
                    user.id, 'SUSPICIOUS_ACTIVITY_BLOCKED', 
                    get_remote_address(), request.headers.get('User-Agent', '')
                )
                return {"error": "Access temporarily restricted"}, 429
                
            return f(*args, **kwargs)
            
        except Exception as e:
            logger.error(f"Session validation error: {e}")
            return {"error": "Authentication failed"}, 401
    
    return decorated_function

def _is_suspicious_activity(user_id, ip_address):
    """Check for suspicious activity patterns."""
    try:
        # Implement Redis-based rate limiting per user
        # This is a placeholder - implement based on your needs
        return False
    except Exception:
        return False

def sanitize_system_data(data):
    """Remove or mask sensitive system information."""
    sensitive_keys = ['networkStats', 'cpuFrequency', 'processCount']
    sanitized = data.copy()
    
    for key in sensitive_keys:
        if key in sanitized:
            sanitized[key] = "[REDACTED]"
    
    # Round/approximate values to prevent fingerprinting
    if 'cpuLoad' in sanitized:
        sanitized['cpuLoad'] = round(sanitized['cpuLoad'] / 5) * 5
    if 'memoryUsage' in sanitized:
        sanitized['memoryUsage'] = round(sanitized['memoryUsage'] / 10) * 10
        
    return sanitized

class UnifiedStatsResource(Resource):
    """Unified stats endpoint that handles all user roles with proper authorization."""
    decorators = [limiter.limit("20 per minute"), validate_user_session]
    
    def get(self):
        """Get statistics based on user role with enhanced security."""
        start_time = time.time()
        
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)
            
            # Security audit log
            security_audit_log(
                user.id, 'STATS_ACCESS', 
                get_remote_address(), request.headers.get('User-Agent', ''),
                f"role:{user.role.value}"
            )
            
            # Role-based data access
            if user.role == UserRole.ATTENDEE:
                stats = self._get_attendee_stats()
            elif user.role == UserRole.ORGANIZER:
                stats = self._get_organizer_stats(user)
            elif user.role == UserRole.ADMIN:
                # Check if detailed stats are requested
                detailed = request.args.get('detailed', 'false').lower() == 'true'
                if detailed:
                    stats = self._get_admin_detailed_stats()
                else:
                    stats = self._get_admin_basic_stats()
            else:
                security_audit_log(
                    user.id, 'INVALID_ROLE_ACCESS', 
                    get_remote_address(), request.headers.get('User-Agent', ''),
                    f"invalid_role:{user.role}"
                )
                return {"error": "Invalid user role"}, 403
            
            # Add timing info for monitoring
            processing_time = time.time() - start_time
            if processing_time > 2.0:  # Log slow queries
                logger.warning(f"Slow stats query: {processing_time:.2f}s for user {user.id}")
            
            return stats, 200
            
        except Exception as e:
            logger.error(f"Error in stats endpoint: {str(e)}")
            security_audit_log(
                identity if 'identity' in locals() else 'unknown', 
                'STATS_ERROR', 
                get_remote_address(), request.headers.get('User-Agent', ''),
                'internal_error'
            )
            return {"error": "Service temporarily unavailable"}, 503

    def _get_attendee_stats(self):
        """Minimal stats for attendees - public information only."""
        try:
            today = datetime.utcnow().date()
            
            # Only basic, non-sensitive platform metrics
            total_events = db.session.query(func.count(Event.id)).scalar()
            upcoming_events = db.session.query(func.count(Event.id)).filter(
                Event.date >= today
            ).scalar()
            
            return {
                "userRole": "attendee",
                "platformStats": {
                    "totalEvents": total_events or 0,
                    "upcomingEvents": upcoming_events or 0,
                },
                "lastUpdated": datetime.utcnow().isoformat(),
                "apiVersion": "2.0"
            }
        except Exception as e:
            logger.error(f"Error fetching attendee stats: {e}")
            return {"error": "Unable to fetch statistics"}, 500

    def _get_organizer_stats(self, user):
        """Stats for organizers - their own data only with data isolation."""
        try:
            organizer = db.session.query(Organizer).filter_by(user_id=user.id).first()
            if not organizer:
                return {"error": "Organizer profile not found"}, 404
            
            today = datetime.utcnow().date()
            
            # Platform stats (non-sensitive)
            total_events = db.session.query(func.count(Event.id)).scalar()
            upcoming_events = db.session.query(func.count(Event.id)).filter(
                Event.date >= today
            ).scalar()
            
            # Organizer's own stats only - strict data isolation
            organizer_events = db.session.query(func.count(Event.id)).filter(
                Event.organizer_id == organizer.id
            ).scalar()
            
            organizer_upcoming = db.session.query(func.count(Event.id)).filter(
                Event.organizer_id == organizer.id,
                Event.date >= today
            ).scalar()
            
            # Fixed revenue calculation - use amount_paid instead of amount
            organizer_revenue = db.session.query(
                func.coalesce(func.sum(Transaction.amount_paid), 0)
            ).join(
                Ticket, Transaction.id == Ticket.transaction_id
            ).join(
                TicketType, Ticket.ticket_type_id == TicketType.id
            ).join(
                Event, TicketType.event_id == Event.id
            ).filter(
                Event.organizer_id == organizer.id,
                Transaction.payment_status.in_([PaymentStatus.COMPLETED, PaymentStatus.PAID])
            ).scalar()
            
            return {
                "userRole": "organizer",
                "platformStats": {
                    "totalEvents": total_events or 0,
                    "upcomingEvents": upcoming_events or 0,
                },
                "organizerStats": {
                    "myEvents": organizer_events or 0,
                    "myUpcomingEvents": organizer_upcoming or 0,
                    "myRevenue": float(organizer_revenue or 0),
                },
                "lastUpdated": datetime.utcnow().isoformat(),
                "apiVersion": "2.0"
            }
            
        except Exception as e:
            logger.error(f"Error fetching organizer stats: {e}")
            return {"error": "Unable to fetch statistics"}, 500

    def _get_admin_basic_stats(self):
        """Basic admin stats with security controls."""
        try:
            # System metrics (sanitized)
            cpu = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Database stats with optimized queries
            total_users = db.session.query(func.count(User.id)).scalar()
            total_events = db.session.query(func.count(Event.id)).scalar()
            total_organizers = db.session.query(func.count(Organizer.id)).scalar()
            
            # Active users (last 30 days)
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            active_users = db.session.query(func.count(User.id)).filter(
                User.created_at >= thirty_days_ago
            ).scalar()
            
            # Fixed revenue calculation
            total_revenue = db.session.query(
                func.coalesce(func.sum(Transaction.amount_paid), 0)
            ).filter(
                Transaction.payment_status.in_([PaymentStatus.PAID, PaymentStatus.COMPLETED])
            ).scalar()
            
            stats = {
                "userRole": "admin",
                "systemHealth": {
                    "cpuLoad": round(cpu, 1),
                    "memoryUsage": round(memory.percent, 1),
                    "diskUsage": round((disk.used / disk.total) * 100, 1),
                    "status": "healthy" if cpu < 80 and memory.percent < 80 else "warning"
                },
                "businessMetrics": {
                    "totalUsers": total_users or 0,
                    "activeUsers": active_users or 0,
                    "totalEvents": total_events or 0,
                    "totalOrganizers": total_organizers or 0,
                    "totalRevenue": float(total_revenue or 0),
                },
                "lastUpdated": datetime.utcnow().isoformat(),
                "apiVersion": "2.0"
            }
            
            return sanitize_system_data(stats)
            
        except Exception as e:
            logger.error(f"Error fetching admin basic stats: {e}")
            return {"error": "Unable to fetch statistics"}, 500

    def _get_admin_detailed_stats(self):
        """Detailed admin stats with comprehensive metrics."""
        try:
            # Get basic stats first
            basic_stats = self._get_admin_basic_stats()
            if "error" in basic_stats:
                return basic_stats
            
            # Add detailed metrics
            detailed_metrics = {
                "revenueByMonth": self._get_revenue_by_month(),
                "transactionMetrics": self._get_transaction_metrics(),
                "eventMetrics": self._get_event_metrics(),
                "userGrowth": self._get_user_growth_stats()
            }
            
            # Merge basic and detailed stats
            basic_stats.update(detailed_metrics)
            basic_stats["detailed"] = True
            
            return basic_stats
            
        except Exception as e:
            logger.error(f"Error fetching admin detailed stats: {e}")
            return {"error": "Unable to fetch detailed statistics"}, 500

    def _get_revenue_by_month(self):
        """Get revenue breakdown by month for current year."""
        try:
            current_year = datetime.now().year
            revenue_by_month = []

            for month in range(1, 13):
                start_date = datetime(current_year, month, 1)
                last_day = calendar.monthrange(current_year, month)[1]
                end_date = datetime(current_year, month, last_day, 23, 59, 59)

                # Fixed: use amount_paid instead of amount
                monthly_revenue = db.session.query(
                    func.coalesce(func.sum(Transaction.amount_paid), 0)
                ).filter(
                    Transaction.timestamp >= start_date,
                    Transaction.timestamp <= end_date,
                    Transaction.payment_status.in_([PaymentStatus.PAID, PaymentStatus.COMPLETED])
                ).scalar()

                revenue_by_month.append({
                    "month": f"{current_year}-{month:02}",
                    "revenue": float(monthly_revenue or 0)
                })

            return revenue_by_month
        except Exception as e:
            logger.error(f"Error calculating monthly revenue: {e}")
            return []

    def _get_transaction_metrics(self):
        """Get transaction-related metrics."""
        try:
            total_transactions = db.session.query(func.count(Transaction.id)).scalar()
            
            successful_transactions = db.session.query(func.count(Transaction.id)).filter(
                Transaction.payment_status.in_([PaymentStatus.PAID, PaymentStatus.COMPLETED])
            ).scalar()
            
            pending_transactions = db.session.query(func.count(Transaction.id)).filter(
                Transaction.payment_status == PaymentStatus.PENDING
            ).scalar()
            
            failed_transactions = db.session.query(func.count(Transaction.id)).filter(
                Transaction.payment_status.in_([PaymentStatus.FAILED, PaymentStatus.CANCELLED])
            ).scalar()
            
            return {
                "totalTransactions": total_transactions or 0,
                "successfulTransactions": successful_transactions or 0,
                "pendingTransactions": pending_transactions or 0,
                "failedTransactions": failed_transactions or 0,
                "successRate": round((successful_transactions / max(total_transactions, 1)) * 100, 2)
            }
        except Exception as e:
            logger.error(f"Error calculating transaction metrics: {e}")
            return {}

    def _get_event_metrics(self):
        """Get event-related metrics."""
        try:
            today = datetime.utcnow().date()
            
            active_events = db.session.query(func.count(Event.id)).filter(
                Event.start_date <= today,
                Event.end_date >= today
            ).scalar()
            
            past_events = db.session.query(func.count(Event.id)).filter(
                Event.end_date < today
            ).scalar()
            
            future_events = db.session.query(func.count(Event.id)).filter(
                Event.start_date > today
            ).scalar()
            
            return {
                "activeEvents": active_events or 0,
                "pastEvents": past_events or 0,
                "futureEvents": future_events or 0
            }
        except Exception as e:
            logger.error(f"Error calculating event metrics: {e}")
            return {}

    def _get_user_growth_stats(self):
        """Get user growth statistics."""
        try:
            # Users registered in last 7 days
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            weekly_users = db.session.query(func.count(User.id)).filter(
                User.created_at >= seven_days_ago
            ).scalar()
            
            # Users registered in last 30 days
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            monthly_users = db.session.query(func.count(User.id)).filter(
                User.created_at >= thirty_days_ago
            ).scalar()
            
            return {
                "newUsersThisWeek": weekly_users or 0,
                "newUsersThisMonth": monthly_users or 0
            }
        except Exception as e:
            logger.error(f"Error calculating user growth: {e}")
            return {}


class SystemHealthResource(Resource):
    """Dedicated system health endpoint for monitoring."""
    decorators = [limiter.limit("30 per minute")]
    
    @jwt_required()
    def get(self):
        """Get system health metrics (admin only)."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)
            
            if user.role != UserRole.ADMIN:
                return {"error": "Admin access required"}, 403
            
            # System metrics
            cpu = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Database connection test
            db_healthy = True
            try:
                db.session.execute(text("SELECT 1")).fetchone()
            except Exception:
                db_healthy = False
            
            health_status = {
                "overall": "healthy",
                "timestamp": datetime.utcnow().isoformat(),
                "system": {
                    "cpu": round(cpu, 1),
                    "memory": round(memory.percent, 1),
                    "disk": round((disk.used / disk.total) * 100, 1)
                },
                "services": {
                    "database": "healthy" if db_healthy else "unhealthy",
                    "redis": "unknown"  # Add Redis check if needed
                }
            }
            
            # Determine overall health
            if cpu > 90 or memory.percent > 90 or not db_healthy:
                health_status["overall"] = "unhealthy"
            elif cpu > 80 or memory.percent > 80:
                health_status["overall"] = "warning"
            
            status_code = 200 if health_status["overall"] in ["healthy", "warning"] else 503
            return health_status, status_code
            
        except Exception as e:
            logger.error(f"Error in health check: {e}")
            return {"error": "Health check failed"}, 503


def register_unified_stats_resources(api):
    """Register unified statistics resources."""
    # Main stats endpoint - handles all roles
    api.add_resource(UnifiedStatsResource, "/api/stats")
    
    # Dedicated health endpoint for monitoring
    api.add_resource(SystemHealthResource, "/api/system/health")


# Security middleware and utilities
class SecurityMiddleware:
    """Additional security middleware for the application."""
    
    @staticmethod
    def validate_request_headers(request):
        """Validate request headers for security."""
        # Check for required security headers
        # Implement CSP, CSRF protection, etc.
        pass
    
    @staticmethod
    def log_suspicious_patterns(user_id, endpoint, params):
        """Detect and log suspicious access patterns."""
        # Implement pattern detection
        pass