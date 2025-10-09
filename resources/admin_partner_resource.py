"""
Enhanced Admin Partner Management Resource with AI Co-pilot
Comprehensive AI assistance for admin oversight, system-wide analytics, and strategic insights
Provides cross-organizer analysis, platform-wide trends, and advanced partner intelligence
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Dict
from flask import request
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import func, desc, and_, or_
from model import (
    db, Event, User, UserRole, Organizer, Partner,
    EventCollaboration, CollaborationType, AIPartnerInsight,
    AIPartnerMatchRecommendation
)
from ai.partner_assistant import partner_assistant

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AdminPartnerOverviewResource(Resource):
    """Admin-only resource for comprehensive partner and collaboration oversight with AI insights."""

    @jwt_required()
    def get(self, overview_type='partners', entity_id=None):
        """
        Get comprehensive admin overview with AI insights:
        - GET /admin/partners -> All partners overview (paginated + sorting + AI insights)
        - GET /admin/partners/<partner_id> -> Single partner detail with AI analysis
        - GET /admin/partners/collaborations -> All collaborations overview (paginated + sorting)
        - GET /admin/partners/collaborations/event/<event_id> -> All collabs for specific event
        - GET /admin/partners/recent -> Recent collaborations with AI trends
        - GET /admin/partners/inactive -> Inactive partners + collaborations with recommendations
        - GET /admin/partners/analytics -> Partnership analytics with AI insights
        """
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)
            if not user or user.role != UserRole.ADMIN:
                return {"message": "Admin access required"}, 403

            # Check for AI insights flag
            include_ai_insights = request.args.get('include_ai_insights', 'true').lower() == 'true'

            if overview_type == 'partners':
                if entity_id:
                    return self._get_partner_detail(entity_id, include_ai_insights)
                return self._get_partners_overview(include_ai_insights)
            elif overview_type == 'collaborations':
                if entity_id:
                    return self._get_event_collaborations(entity_id, include_ai_insights)
                return self._get_collaborations_overview(include_ai_insights)
            elif overview_type == 'recent':
                return self._get_recent_collaborations(include_ai_insights)
            elif overview_type == 'inactive':
                return self._get_inactive_overview(include_ai_insights)
            elif overview_type == 'analytics':
                return self._get_partnership_analytics(include_ai_insights)
            else:
                return {"message": "Invalid overview type"}, 400
        except Exception as e:
            logger.error(f"Error in AdminPartnerOverviewResource: {str(e)}")
            return {"message": "Error fetching admin overview"}, 500

    def _get_partners_overview(self, include_ai_insights):
        """Get overview of all partners with pagination, sorting, and AI insights."""
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 12, type=int), 50)
        sort_by = request.args.get('sort_by', 'id')
        order = request.args.get('order', 'asc')
        organizer_filter = request.args.get('organizer_id', type=int)
        performance_filter = request.args.get('min_performance', type=float)
        search = request.args.get('search')

        query = Partner.query

        # Apply filters
        if organizer_filter:
            query = query.filter_by(organizer_id=organizer_filter)

        if performance_filter:
            query = query.filter(Partner.performance_score >= performance_filter)

        if search:
            query = query.filter(Partner.company_name.ilike(f"%{search}%"))

        # Apply sorting
        if sort_by == 'name':
            query = query.order_by(Partner.company_name.asc() if order == 'asc' else Partner.company_name.desc())
        elif sort_by == 'active':
            query = query.order_by(Partner.is_active.asc() if order == 'asc' else Partner.is_active.desc())
        elif sort_by == 'performance':
            query = query.order_by(Partner.performance_score.asc() if order == 'asc' else Partner.performance_score.desc())
        elif sort_by == 'created_at':
            query = query.order_by(Partner.created_at.asc() if order == 'asc' else Partner.created_at.desc())
        else:
            query = query.order_by(Partner.id.asc() if order == 'asc' else Partner.id.desc())

        partners = query.paginate(page=page, per_page=per_page, error_out=False)

        partners_data = []
        for partner in partners.items:
            partner_dict = {
                **partner.as_dict(),
                "collaborations_count": EventCollaboration.query.filter_by(partner_id=partner.id).count(),
                "active_collaborations_count": EventCollaboration.query.filter_by(
                    partner_id=partner.id,
                    is_active=True
                ).count(),
                "organizer_name": partner.organizer.company_name if partner.organizer else None,
                "active": partner.is_active
            }

            # Add AI insights if requested
            if include_ai_insights:
                try:
                    # Get latest insight
                    latest_insight = AIPartnerInsight.query.filter_by(
                        partner_id=partner.id,
                        is_active=True
                    ).order_by(AIPartnerInsight.created_at.desc()).first()

                    if latest_insight:
                        partner_dict['latest_ai_insight'] = {
                            'insight_type': latest_insight.insight_type,
                            'priority': latest_insight.priority,
                            'title': latest_insight.title,
                            'confidence_score': latest_insight.confidence_score
                        }
                except Exception as e:
                    logger.error(f"Error fetching AI insight for partner {partner.id}: {e}")

            partners_data.append(partner_dict)

        result = {
            "partners": partners_data,
            "total": partners.total,
            "pages": partners.pages,
            "current_page": partners.page,
            "per_page": partners.per_page,
            "has_next": partners.has_next,
            "has_prev": partners.has_prev,
            "sort_by": sort_by,
            "order": order,
            "filters": {
                "organizer_id": organizer_filter,
                "min_performance": performance_filter,
                "search": search
            }
        }

        # Add platform-wide AI insights
        if include_ai_insights:
            try:
                result['platform_insights'] = self._get_platform_insights()
                result['ai_actions'] = {
                    'bulk_analyze_all': 'POST /admin/partners/ai/bulk-analyze-all',
                    'platform_trends': 'GET /admin/partners/ai/platform-trends',
                    'quality_audit': 'POST /admin/partners/ai/quality-audit',
                    'natural_query': 'POST /admin/partners/ai/assist'
                }
            except Exception as e:
                logger.error(f"Error generating platform insights: {e}")

        return result, 200

    def _get_partner_detail(self, partner_id, include_ai_insights):
        """Get full detail for one partner with AI analysis."""
        partner = Partner.query.get(partner_id)
        if not partner:
            return {"message": "Partner not found"}, 404

        collaborations = (
            EventCollaboration.query.filter_by(partner_id=partner.id)
            .join(Event)
            .order_by(EventCollaboration.created_at.desc())
            .all()
        )

        partner_data = partner.as_dict()
        partner_data['collaborations'] = [
            {
                **collab.as_dict(),
                "event_title": collab.event.name,
                "event_date": collab.event.date.isoformat() if collab.event.date else None,
                "organizer_name": collab.event.organizer.company_name if collab.event.organizer else None,
            } for collab in collaborations
        ]
        partner_data['collaborations_count'] = len(collaborations)
        partner_data['organizer'] = {
            'id': partner.organizer.id,
            'company_name': partner.organizer.company_name
        } if partner.organizer else None

        # Add comprehensive AI analysis
        if include_ai_insights:
            try:
                # Performance analysis
                performance = partner_assistant.analyze_partner_performance(partner_id)
                if performance:
                    partner_data['ai_performance_analysis'] = performance

                # All insights history
                all_insights = AIPartnerInsight.query.filter_by(
                    partner_id=partner_id
                ).order_by(AIPartnerInsight.created_at.desc()).limit(10).all()

                partner_data['ai_insights_history'] = [
                    {
                        'id': insight.id,
                        'type': insight.insight_type,
                        'title': insight.title,
                        'priority': insight.priority,
                        'created_at': insight.created_at.isoformat(),
                        'is_read': insight.is_read
                    }
                    for insight in all_insights
                ]

                # Match recommendations
                recommendations = AIPartnerMatchRecommendation.query.filter_by(
                    partner_id=partner_id,
                    is_active=True
                ).order_by(AIPartnerMatchRecommendation.match_score.desc()).all()

                partner_data['ai_recommendations'] = [
                    {
                        'event_id': rec.event_id,
                        'event_name': rec.event.name if rec.event else None,
                        'match_score': rec.match_score,
                        'suggested_type': rec.suggested_collaboration_type.value,
                        'reason': rec.match_reason
                    }
                    for rec in recommendations[:5]
                ]

                # Cross-organizer comparison
                partner_data['benchmark_data'] = self._get_partner_benchmark(partner)

                partner_data['admin_ai_actions'] = {
                    'regenerate_analysis': f'POST /admin/partners/{partner_id}/ai/analyze',
                    'enhance_description': f'POST /admin/partners/{partner_id}/ai/enhance',
                    'quality_check': f'POST /admin/partners/{partner_id}/ai/quality-check',
                    'cross_organizer_insights': f'GET /admin/partners/{partner_id}/ai/cross-organizer'
                }
            except Exception as e:
                logger.error(f"Error adding AI insights to partner detail: {e}")

        return {
            'partner': partner_data
        }, 200

    def _get_collaborations_overview(self, include_ai_insights):
        """Get overview of all collaborations with AI insights."""
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 12, type=int), 50)
        sort_by = request.args.get('sort_by', 'id')
        order = request.args.get('order', 'asc')
        status_filter = request.args.get('status')
        collab_type_filter = request.args.get('collaboration_type')

        query = EventCollaboration.query.join(Event).join(Partner)

        # Apply filters
        if status_filter:
            if status_filter == 'active':
                query = query.filter(EventCollaboration.is_active == True)
            elif status_filter == 'inactive':
                query = query.filter(EventCollaboration.is_active == False)

        if collab_type_filter:
            try:
                collab_type = CollaborationType(collab_type_filter)
                query = query.filter(EventCollaboration.collaboration_type == collab_type)
            except ValueError:
                pass

        # Apply sorting
        if sort_by == 'event_date':
            query = query.order_by(Event.date.asc() if order == 'asc' else Event.date.desc())
        elif sort_by == 'partner_name':
            query = query.order_by(Partner.company_name.asc() if order == 'asc' else Partner.company_name.desc())
        elif sort_by == 'created_at':
            query = query.order_by(EventCollaboration.created_at.asc() if order == 'asc' else EventCollaboration.created_at.desc())
        elif sort_by == 'contribution_score':
            query = query.order_by(EventCollaboration.contribution_score.asc() if order == 'asc' else EventCollaboration.contribution_score.desc())
        else:
            query = query.order_by(EventCollaboration.id.asc() if order == 'asc' else EventCollaboration.id.desc())

        collaborations = query.paginate(page=page, per_page=per_page, error_out=False)

        collabs_data = []
        for collab in collaborations.items:
            collab_dict = {
                **collab.as_dict(),
                "event_title": collab.event.name,
                "partner_name": collab.partner.company_name if collab.partner else None,
                "event_date": collab.event.date.isoformat() if collab.event.date else None,
                "organizer_name": collab.event.organizer.company_name if collab.event.organizer else None
            }

            # Add AI optimization insights
            if include_ai_insights and collab.contribution_score:
                if collab.contribution_score < 0.4:
                    collab_dict['ai_flag'] = {
                        'type': 'needs_attention',
                        'message': 'Low contribution score - may need optimization',
                        'action': f'POST /admin/partners/collaborations/{collab.id}/ai/optimize'
                    }
                elif collab.contribution_score > 0.8:
                    collab_dict['ai_flag'] = {
                        'type': 'high_performer',
                        'message': 'Excellent performance - good case study candidate'
                    }

            collabs_data.append(collab_dict)

        result = {
            "collaborations": collabs_data,
            "total": collaborations.total,
            "pages": collaborations.pages,
            "current_page": collaborations.page,
            "per_page": collaborations.per_page,
            "has_next": collaborations.has_next,
            "has_prev": collaborations.has_prev,
            "sort_by": sort_by,
            "order": order,
            "filters": {
                "status": status_filter,
                "collaboration_type": collab_type_filter
            }
        }

        # Add collaboration insights
        if include_ai_insights:
            try:
                result['collaboration_insights'] = self._get_collaboration_insights()
                result['ai_actions'] = {
                    'bulk_optimize': 'POST /admin/partners/ai/bulk-optimize-collaborations',
                    'identify_issues': 'GET /admin/partners/ai/collaboration-issues',
                    'success_patterns': 'GET /admin/partners/ai/success-patterns'
                }
            except Exception as e:
                logger.error(f"Error generating collaboration insights: {e}")

        return result, 200

    def _get_event_collaborations(self, event_id, include_ai_insights):
        """Get all collaborations for a given event with AI recommendations."""
        event = Event.query.get(event_id)
        if not event:
            return {"message": "Event not found"}, 404

        collaborations = EventCollaboration.query.filter_by(event_id=event.id).join(Partner).all()

        result = {
            "event": event.as_dict(),
            "collaborations": [
                {
                    **collab.as_dict(),
                    "partner": collab.partner.as_dict() if collab.partner else None
                } for collab in collaborations
            ],
            "total": len(collaborations)
        }

        # Add AI suggestions for improvement
        if include_ai_insights:
            try:
                # Get potential additional partners
                suggestions = partner_assistant.suggest_collaborations_for_event(event_id, limit=5)
                if suggestions:
                    result['ai_suggested_partners'] = suggestions

                # Analyze existing collaborations
                optimization_opportunities = []
                for collab in collaborations:
                    if collab.contribution_score and collab.contribution_score < 0.5:
                        optimization_opportunities.append({
                            'collaboration_id': collab.id,
                            'partner_name': collab.partner.company_name if collab.partner else None,
                            'issue': 'Below average contribution score',
                            'action': f'POST /admin/partners/collaborations/{collab.id}/ai/optimize'
                        })

                if optimization_opportunities:
                    result['optimization_opportunities'] = optimization_opportunities

            except Exception as e:
                logger.error(f"Error generating AI recommendations for event: {e}")

        return result, 200

    def _get_recent_collaborations(self, include_ai_insights, limit=20):
        """Get most recent collaborations with trend analysis."""
        collaborations = (
            EventCollaboration.query
            .order_by(EventCollaboration.created_at.desc())
            .limit(limit)
            .all()
        )

        result = {
            "recent_collaborations": [
                {
                    **collab.as_dict(),
                    "event_title": collab.event.name,
                    "partner_name": collab.partner.company_name if collab.partner else None,
                    "organizer_name": collab.event.organizer.company_name if collab.event.organizer else None
                } for collab in collaborations
            ]
        }

        # Add trend analysis
        if include_ai_insights:
            try:
                # Analyze recent collaboration patterns
                collab_types = {}
                avg_score = 0
                score_count = 0

                for collab in collaborations:
                    ctype = collab.collaboration_type.value
                    collab_types[ctype] = collab_types.get(ctype, 0) + 1

                    if collab.contribution_score:
                        avg_score += collab.contribution_score
                        score_count += 1

                result['recent_trends'] = {
                    'most_common_type': max(collab_types.items(), key=lambda x: x[1])[0] if collab_types else None,
                    'type_distribution': collab_types,
                    'avg_contribution_score': round(avg_score / score_count, 2) if score_count > 0 else None,
                    'trend_direction': 'positive' if (avg_score / score_count if score_count > 0 else 0) > 0.6 else 'needs_attention'
                }

                result['ai_actions'] = {
                    'detailed_trends': 'GET /admin/partners/ai/platform-trends',
                    'predict_success': 'POST /admin/partners/ai/predict-collaboration-success'
                }
            except Exception as e:
                logger.error(f"Error analyzing recent trends: {e}")

        return result, 200

    def _get_inactive_overview(self, include_ai_insights):
        """List inactive partners + collaborations with AI recommendations."""
        inactive_partners = Partner.query.filter_by(is_active=False).all()
        inactive_collabs = EventCollaboration.query.filter_by(is_active=False).all()

        result = {
            "inactive_partners": [p.as_dict() for p in inactive_partners],
            "inactive_collaborations": [c.as_dict() for c in inactive_collabs],
            "totals": {
                "inactive_partners": len(inactive_partners),
                "inactive_collaborations": len(inactive_collabs)
            }
        }

        # Add AI reactivation recommendations
        if include_ai_insights:
            try:
                reactivation_candidates = []

                for partner in inactive_partners:
                    if partner.performance_score and partner.performance_score > 0.6:
                        # High-performing partner that was deactivated
                        stats = partner_assistant._calculate_partner_stats(partner)
                        if stats['total_collaborations'] > 2:
                            reactivation_candidates.append({
                                'partner_id': partner.id,
                                'partner_name': partner.company_name,
                                'reason': 'High past performance',
                                'performance_score': partner.performance_score,
                                'past_collaborations': stats['total_collaborations'],
                                'recommendation': 'Consider reactivating - strong track record'
                            })

                if reactivation_candidates:
                    result['ai_reactivation_candidates'] = reactivation_candidates

                # Analyze why collaborations became inactive
                deactivation_patterns = self._analyze_deactivation_patterns(inactive_collabs)
                result['deactivation_insights'] = deactivation_patterns

            except Exception as e:
                logger.error(f"Error generating reactivation insights: {e}")

        return result, 200

    def _get_partnership_analytics(self, include_ai_insights):
        """Generate comprehensive analytics with AI insights."""
        total_partners = Partner.query.count()
        total_collaborations = EventCollaboration.query.count()
        active_partners = Partner.query.filter_by(is_active=True).count()
        inactive_partners = Partner.query.filter_by(is_active=False).count()
        active_collaborations = EventCollaboration.query.filter_by(is_active=True).count()

        # Calculate average metrics
        all_partners = Partner.query.all()
        perf_scores = [p.performance_score for p in all_partners if p.performance_score]
        avg_performance = sum(perf_scores) / len(perf_scores) if perf_scores else 0

        # Collaboration type distribution
        collab_type_dist = db.session.query(
            EventCollaboration.collaboration_type,
            func.count(EventCollaboration.id)
        ).filter(EventCollaboration.is_active == True).group_by(
            EventCollaboration.collaboration_type
        ).all()

        type_distribution = {ctype.value: count for ctype, count in collab_type_dist}

        # Top performing partners
        top_partners = Partner.query.filter(
            Partner.is_active == True,
            Partner.performance_score.isnot(None)
        ).order_by(Partner.performance_score.desc()).limit(10).all()

        # Organizer-level statistics
        organizer_stats = db.session.query(
            Organizer.id,
            Organizer.company_name,
            func.count(Partner.id).label('partner_count'),
            func.avg(Partner.performance_score).label('avg_performance')
        ).outerjoin(Partner).group_by(Organizer.id, Organizer.company_name).all()

        result = {
            "analytics": {
                "total_partners": total_partners,
                "active_partners": active_partners,
                "inactive_partners": inactive_partners,
                "total_collaborations": total_collaborations,
                "active_collaborations": active_collaborations,
                "avg_collaborations_per_partner": round(
                    total_collaborations / total_partners if total_partners else 0, 2
                ),
                "avg_performance_score": round(avg_performance, 2),
                "collaboration_type_distribution": type_distribution
            },
            "top_performers": [
                {
                    'id': p.id,
                    'company_name': p.company_name,
                    'performance_score': p.performance_score,
                    'organizer': p.organizer.company_name if p.organizer else None
                }
                for p in top_partners
            ],
            "organizer_breakdown": [
                {
                    'organizer_id': org_id,
                    'organizer_name': org_name,
                    'partner_count': count,
                    'avg_performance': round(float(avg_perf), 2) if avg_perf else 0
                }
                for org_id, org_name, count, avg_perf in organizer_stats
            ]
        }

        # Add comprehensive AI analytics
        if include_ai_insights:
            try:
                # Platform-wide health assessment
                health_assessment = self._generate_platform_health_assessment()
                result['platform_health'] = health_assessment

                # Predictive analytics
                growth_prediction = self._predict_platform_growth()
                result['growth_predictions'] = growth_prediction

                # Quality metrics
                quality_metrics = self._calculate_quality_metrics()
                result['quality_metrics'] = quality_metrics

                # Strategic recommendations
                strategic_recs = self._generate_strategic_recommendations()
                result['strategic_recommendations'] = strategic_recs

                result['admin_ai_actions'] = {
                    'deep_dive_analysis': 'POST /admin/partners/ai/deep-analysis',
                    'export_insights': 'GET /admin/partners/ai/export-report',
                    'quality_audit': 'POST /admin/partners/ai/quality-audit',
                    'comparative_analysis': 'GET /admin/partners/ai/comparative-analysis'
                }
            except Exception as e:
                logger.error(f"Error generating AI analytics: {e}")

        return result, 200

    # ==================== AI-POWERED HELPER METHODS ====================

    def _get_platform_insights(self) -> Dict:
        """Generate platform-wide partnership insights"""
        total_partners = Partner.query.filter_by(is_active=True).count()
        total_organizers = Organizer.query.count()

        # Growth metrics
        last_month = datetime.utcnow() - timedelta(days=30)
        new_partners = Partner.query.filter(Partner.created_at >= last_month).count()
        new_collabs = EventCollaboration.query.filter(EventCollaboration.created_at >= last_month).count()

        # Performance distribution
        high_performers = Partner.query.filter(
            Partner.is_active == True,
            Partner.performance_score >= 0.7
        ).count()

        low_performers = Partner.query.filter(
            Partner.is_active == True,
            Partner.performance_score < 0.4
        ).count()

        return {
            'total_active_partners': total_partners,
            'partners_per_organizer': round(total_partners / max(total_organizers, 1), 2),
            'new_partners_last_month': new_partners,
            'new_collaborations_last_month': new_collabs,
            'high_performers_count': high_performers,
            'low_performers_count': low_performers,
            'health_score': self._calculate_platform_health_score()
        }

    def _get_partner_benchmark(self, partner: Partner) -> Dict:
        """Benchmark a partner against platform averages"""
        # Get all partners from the same organizer
        organizer_partners = Partner.query.filter_by(
            organizer_id=partner.organizer_id,
            is_active=True
        ).all()

        # Get platform-wide partners
        all_partners = Partner.query.filter_by(is_active=True).all()

        # Calculate organizer averages
        org_perf_scores = [p.performance_score for p in organizer_partners if p.performance_score]
        org_avg_performance = sum(org_perf_scores) / len(org_perf_scores) if org_perf_scores else 0

        org_collab_counts = [len([c for c in p.collaborations if c.is_active]) for p in organizer_partners]
        org_avg_collabs = sum(org_collab_counts) / len(org_collab_counts) if org_collab_counts else 0

        # Calculate platform averages
        platform_perf_scores = [p.performance_score for p in all_partners if p.performance_score]
        platform_avg_performance = sum(platform_perf_scores) / len(platform_perf_scores) if platform_perf_scores else 0

        platform_collab_counts = [len([c for c in p.collaborations if c.is_active]) for p in all_partners]
        platform_avg_collabs = sum(platform_collab_counts) / len(platform_collab_counts) if platform_collab_counts else 0

        # Partner's metrics
        partner_collabs = len([c for c in partner.collaborations if c.is_active])
        partner_performance = partner.performance_score or 0

        return {
            'partner_performance': round(partner_performance, 2),
            'partner_collaborations': partner_collabs,
            'organizer_avg_performance': round(org_avg_performance, 2),
            'organizer_avg_collaborations': round(org_avg_collabs, 2),
            'platform_avg_performance': round(platform_avg_performance, 2),
            'platform_avg_collaborations': round(platform_avg_collabs, 2),
            'performance_percentile': self._calculate_percentile(partner_performance, platform_perf_scores),
            'collaboration_percentile': self._calculate_percentile(partner_collabs, platform_collab_counts)
        }

    def _calculate_percentile(self, value: float, dataset: list) -> int:
        """Calculate percentile ranking"""
        if not dataset or value is None:
            return 50

        sorted_data = sorted(dataset)
        position = sum(1 for x in sorted_data if x <= value)
        return int((position / len(sorted_data)) * 100)

    def _get_collaboration_insights(self) -> Dict:
        """Generate insights about collaboration patterns"""
        active_collabs = EventCollaboration.query.filter_by(is_active=True).all()

        if not active_collabs:
            return {"message": "No active collaborations to analyze"}

        # Contribution score analysis
        scores = [c.contribution_score for c in active_collabs if c.contribution_score]
        avg_contribution = sum(scores) / len(scores) if scores else 0

        # Type effectiveness analysis
        type_performance = {}
        for collab in active_collabs:
            ctype = collab.collaboration_type.value
            if ctype not in type_performance:
                type_performance[ctype] = {'count': 0, 'avg_score': 0, 'scores': []}

            type_performance[ctype]['count'] += 1
            if collab.contribution_score:
                type_performance[ctype]['scores'].append(collab.contribution_score)

        # Calculate averages
        for ctype in type_performance:
            scores = type_performance[ctype]['scores']
            type_performance[ctype]['avg_score'] = round(sum(scores) / len(scores), 2) if scores else 0
            del type_performance[ctype]['scores']

        # Identify best performing type
        best_type = max(type_performance.items(), key=lambda x: x[1]['avg_score'])[0] if type_performance else None

        return {
            'total_active_collaborations': len(active_collabs),
            'avg_contribution_score': round(avg_contribution, 2),
            'type_performance': type_performance,
            'best_performing_type': best_type,
            'recommendations': self._generate_collaboration_recommendations(type_performance)
        }

    def _generate_collaboration_recommendations(self, type_performance: Dict) -> list:
        """Generate recommendations based on collaboration type performance"""
        recommendations = []

        for ctype, data in type_performance.items():
            if data['avg_score'] < 0.4 and data['count'] > 3:
                recommendations.append({
                    'type': ctype,
                    'issue': 'Below average performance',
                    'suggestion': f'Review and optimize {ctype} collaborations',
                    'affected_count': data['count']
                })
            elif data['avg_score'] > 0.8:
                recommendations.append({
                    'type': ctype,
                    'success': 'High performance',
                    'suggestion': f'Use {ctype} as template for other collaboration types',
                    'count': data['count']
                })

        return recommendations

    def _analyze_deactivation_patterns(self, inactive_collabs: list) -> Dict:
        """Analyze why collaborations became inactive"""
        if not inactive_collabs:
            return {"message": "No inactive collaborations to analyze"}

        # Time-based analysis
        recent_deactivations = []
        old_deactivations = []
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)

        for collab in inactive_collabs:
            if collab.updated_at >= thirty_days_ago:
                recent_deactivations.append(collab)
            else:
                old_deactivations.append(collab)

        # Performance-based analysis
        low_performance_deactivations = [
            c for c in inactive_collabs
            if c.contribution_score and c.contribution_score < 0.3
        ]

        return {
            'total_inactive': len(inactive_collabs),
            'recent_deactivations': len(recent_deactivations),
            'old_deactivations': len(old_deactivations),
            'low_performance_related': len(low_performance_deactivations),
            'pattern_insight': (
                'High recent deactivation rate - investigate causes'
                if len(recent_deactivations) > 5
                else 'Normal deactivation pattern'
            )
        }

    def _generate_platform_health_assessment(self) -> Dict:
        """Generate comprehensive platform health assessment"""
        # Partner health
        total_partners = Partner.query.filter_by(is_active=True).count()
        partners_with_collabs = db.session.query(Partner.id).join(
            EventCollaboration
        ).filter(
            Partner.is_active == True,
            EventCollaboration.is_active == True
        ).distinct().count()

        # Collaboration health
        total_collabs = EventCollaboration.query.filter_by(is_active=True).count()
        healthy_collabs = EventCollaboration.query.filter(
            EventCollaboration.is_active == True,
            EventCollaboration.contribution_score >= 0.6
        ).count()

        # Calculate health scores
        partner_utilization = (partners_with_collabs / max(total_partners, 1)) * 100
        collaboration_health = (healthy_collabs / max(total_collabs, 1)) * 100

        # Overall health score (weighted average)
        overall_health = (partner_utilization * 0.4 + collaboration_health * 0.6)

        # Determine health status
        if overall_health >= 80:
            status = 'excellent'
            message = 'Platform partnerships are thriving'
        elif overall_health >= 60:
            status = 'good'
            message = 'Platform partnerships are healthy with room for improvement'
        elif overall_health >= 40:
            status = 'fair'
            message = 'Platform partnerships need attention and optimization'
        else:
            status = 'poor'
            message = 'Platform partnerships require immediate intervention'

        return {
            'overall_health_score': round(overall_health, 2),
            'status': status,
            'message': message,
            'metrics': {
                'partner_utilization': round(partner_utilization, 2),
                'collaboration_health': round(collaboration_health, 2),
                'active_partners': total_partners,
                'partners_with_active_collabs': partners_with_collabs,
                'healthy_collaborations': healthy_collabs,
                'total_collaborations': total_collabs
            }
        }

    def _predict_platform_growth(self) -> Dict:
        """Predict platform growth based on historical data"""
        now = datetime.utcnow()

        # Get historical data (last 6 months, month by month)
        monthly_data = []
        for i in range(6, 0, -1):
            start_date = now - timedelta(days=30*i)
            end_date = now - timedelta(days=30*(i-1))

            partners_created = Partner.query.filter(
                Partner.created_at >= start_date,
                Partner.created_at < end_date
            ).count()

            collabs_created = EventCollaboration.query.filter(
                EventCollaboration.created_at >= start_date,
                EventCollaboration.created_at < end_date
            ).count()

            monthly_data.append({
                'month': i,
                'partners': partners_created,
                'collaborations': collabs_created
            })

        # Simple linear trend calculation
        if len(monthly_data) >= 3:
            partner_trend = monthly_data[-1]['partners'] - monthly_data[0]['partners']
            collab_trend = monthly_data[-1]['collaborations'] - monthly_data[0]['collaborations']

            # Predict next month
            predicted_partners = max(0, monthly_data[-1]['partners'] + (partner_trend / len(monthly_data)))
            predicted_collabs = max(0, monthly_data[-1]['collaborations'] + (collab_trend / len(monthly_data)))

            trend_direction = 'growing' if partner_trend > 0 else 'declining' if partner_trend < 0 else 'stable'
        else:
            predicted_partners = 0
            predicted_collabs = 0
            trend_direction = 'insufficient_data'

        return {
            'historical_data': monthly_data[-3:],  # Last 3 months
            'trend_direction': trend_direction,
            'predictions_next_month': {
                'new_partners': int(predicted_partners),
                'new_collaborations': int(predicted_collabs)
            },
            'confidence': 'medium' if len(monthly_data) >= 3 else 'low'
        }

    def _calculate_quality_metrics(self) -> Dict:
        """Calculate partnership quality metrics"""
        all_partners = Partner.query.filter_by(is_active=True).all()

        # Description quality
        partners_with_description = sum(1 for p in all_partners if p.company_description)
        ai_enhanced = sum(1 for p in all_partners if p.ai_description_enhanced)

        # Contact info completeness
        partners_with_contact = sum(
            1 for p in all_partners
            if p.contact_email or p.contact_person
        )

        # Logo availability
        partners_with_logo = sum(1 for p in all_partners if p.logo_url)

        # Website availability
        partners_with_website = sum(1 for p in all_partners if p.website_url)

        total = max(len(all_partners), 1)

        # Calculate quality score (0-100)
        quality_score = (
            (partners_with_description / total) * 25 +
            (partners_with_contact / total) * 25 +
            (partners_with_logo / total) * 25 +
            (partners_with_website / total) * 25
        )

        return {
            'overall_quality_score': round(quality_score, 2),
            'completeness_metrics': {
                'with_description': round((partners_with_description / total) * 100, 2),
                'with_contact_info': round((partners_with_contact / total) * 100, 2),
                'with_logo': round((partners_with_logo / total) * 100, 2),
                'with_website': round((partners_with_website / total) * 100, 2)
            },
            'ai_enhancement': {
                'ai_enhanced_count': ai_enhanced,
                'ai_enhancement_rate': round((ai_enhanced / total) * 100, 2)
            },
            'quality_grade': (
                'A' if quality_score >= 90 else
                'B' if quality_score >= 75 else
                'C' if quality_score >= 60 else
                'D' if quality_score >= 40 else 'F'
            )
        }

    def _generate_strategic_recommendations(self) -> list:
        """Generate strategic recommendations for platform improvement"""
        recommendations = []

        # Check partner distribution
        organizer_partner_counts = db.session.query(
            func.count(Partner.id)
        ).filter(
            Partner.is_active == True
        ).group_by(Partner.organizer_id).all()

        if organizer_partner_counts:
            avg_partners = sum(count[0] for count in organizer_partner_counts) / len(organizer_partner_counts)

            if avg_partners < 3:
                recommendations.append({
                    'priority': 'high',
                    'area': 'Partner Growth',
                    'recommendation': 'Average organizer has fewer than 3 partners. Promote partner onboarding.',
                    'expected_impact': 'Increased platform engagement and event support'
                })

        # Check collaboration health
        low_performing_collabs = EventCollaboration.query.filter(
            EventCollaboration.is_active == True,
            EventCollaboration.contribution_score < 0.4
        ).count()

        total_collabs = EventCollaboration.query.filter_by(is_active=True).count()

        if total_collabs > 0 and (low_performing_collabs / total_collabs) > 0.2:
            recommendations.append({
                'priority': 'high',
                'area': 'Collaboration Optimization',
                'recommendation': f'{round((low_performing_collabs/total_collabs)*100)}% of collaborations are underperforming. Implement optimization program.',
                'expected_impact': 'Improved partnership ROI and satisfaction'
            })

        # Check AI adoption
        ai_insights_count = AIPartnerInsight.query.filter_by(is_active=True).count()
        total_partners = Partner.query.filter_by(is_active=True).count()

        if total_partners > 0 and ai_insights_count < total_partners * 0.5:
            recommendations.append({
                'priority': 'medium',
                'area': 'AI Adoption',
                'recommendation': 'Less than 50% of partners have AI insights. Encourage organizers to use AI features.',
                'expected_impact': 'Better decision-making and partner management'
            })

        # Check inactive partner recovery
        inactive_partners = Partner.query.filter_by(is_active=False).count()
        if inactive_partners > total_partners * 0.3:
            recommendations.append({
                'priority': 'medium',
                'area': 'Partner Retention',
                'recommendation': f'{inactive_partners} inactive partners. Review deactivation reasons and consider reactivation campaigns.',
                'expected_impact': 'Recovered partnerships and increased platform value'
            })

        return recommendations

    def _calculate_platform_health_score(self) -> float:
        """Calculate overall platform health score"""
        scores = []

        # Active partner ratio
        total = Partner.query.count()
        active = Partner.query.filter_by(is_active=True).count()
        if total > 0:
            scores.append((active / total) * 100)

        # Active collaboration ratio
        total_collabs = EventCollaboration.query.count()
        active_collabs = EventCollaboration.query.filter_by(is_active=True).count()
        if total_collabs > 0:
            scores.append((active_collabs / total_collabs) * 100)

        # Average performance score
        all_partners = Partner.query.filter_by(is_active=True).all()
        perf_scores = [p.performance_score * 100 for p in all_partners if p.performance_score]
        if perf_scores:
            scores.append(sum(perf_scores) / len(perf_scores))

        return round(sum(scores) / len(scores), 2) if scores else 50.0

class AdminPartnerAIAssistResource(Resource):
    """Admin AI Co-pilot for advanced partnership analysis"""

    @jwt_required()
    def post(self):
        """Process natural language admin queries about platform-wide partnerships"""
        identity = get_jwt_identity()
        user = User.query.get(identity)

        if not user or user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403

        data = request.get_json()
        query = data.get('query')

        if not query:
            return {"message": "Query is required"}, 400

        # Process query with admin context
        result = partner_assistant.process_natural_language_query(query, None)

        # Enhance with admin-specific actions
        intent = result.get('intent')

        if intent == 'analyze_partner':
            result['admin_actions'] = {
                "cross_organizer_analysis": "GET /admin/partners/{id}/ai/cross-organizer",
                "platform_benchmark": "GET /admin/partners/{id}/ai/benchmark",
                "quality_audit": "POST /admin/partners/{id}/ai/quality-check"
            }

        elif intent == 'performance_report':
            result['admin_actions'] = {
                "platform_report": "GET /admin/partners/ai/platform-report",
                "comparative_analysis": "GET /admin/partners/ai/comparative-analysis",
                "export_data": "GET /admin/partners/ai/export-report"
            }

        elif intent == 'list_partners':
            result['admin_actions'] = {
                "quality_audit_all": "POST /admin/partners/ai/quality-audit",
                "bulk_analyze_platform": "POST /admin/partners/ai/bulk-analyze-all",
                "identify_issues": "GET /admin/partners/ai/platform-issues"
            }

        return result, 200

class AdminPartnerAnalysisResource(Resource):
    """Admin-level partner analysis with cross-organizer insights"""

    @jwt_required()
    def post(self, partner_id):
        """Generate admin-level analysis for a partner"""
        identity = get_jwt_identity()
        user = User.query.get(identity)

        if not user or user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403

        partner = Partner.query.get(partner_id)
        if not partner:
            return {"message": "Partner not found"}, 404

        # Generate comprehensive analysis
        analysis = partner_assistant.analyze_partner_performance(partner_id)

        if not analysis:
            return {"message": "Could not generate analysis"}, 500

        # Add admin-specific insights
        analysis['benchmark_data'] = AdminPartnerOverviewResource()._get_partner_benchmark(partner)
        analysis['cross_organizer_comparison'] = self._get_cross_organizer_insights(partner)

        return {
            "action": "admin_analysis_complete",
            "analysis": analysis,
            "admin_actions": {
                "flag_for_review": f"POST /admin/partners/{partner_id}/flag",
                "quality_check": f"POST /admin/partners/{partner_id}/ai/quality-check",
                "export_report": f"GET /admin/partners/{partner_id}/ai/export"
            }
        }, 200

    def _get_cross_organizer_insights(self, partner: Partner) -> Dict:
        """Compare partner performance across similar partners from other organizers"""
        # Find similar partners from other organizers
        similar_partners = Partner.query.filter(
            Partner.organizer_id != partner.organizer_id,
            Partner.is_active == True
        ).limit(50).all()

        # Calculate metrics
        if similar_partners:
            perf_scores = [p.performance_score for p in similar_partners if p.performance_score]
            collab_counts = [len([c for c in p.collaborations if c.is_active]) for p in similar_partners]

            return {
                'comparison_pool_size': len(similar_partners),
                'platform_avg_performance': round(sum(perf_scores) / len(perf_scores), 2) if perf_scores else 0,
                'platform_avg_collaborations': round(sum(collab_counts) / len(collab_counts), 2) if collab_counts else 0,
                'partner_rank': self._calculate_rank(partner, similar_partners)
            }

        return {'message': 'Insufficient data for cross-organizer comparison'}

    def _calculate_rank(self, partner: Partner, comparison_partners: list) -> str:
        """Calculate partner's rank among comparison set"""
        if not partner.performance_score:
            return 'unranked'

        better_partners = sum(
            1 for p in comparison_partners
            if p.performance_score and p.performance_score > partner.performance_score
        )

        total = len([p for p in comparison_partners if p.performance_score])

        if total == 0:
            return 'unranked'

        percentile = ((total - better_partners) / total) * 100

        if percentile >= 90:
            return 'top_10_percent'
        elif percentile >= 75:
            return 'top_25_percent'
        elif percentile >= 50:
            return 'above_average'
        else:
            return 'below_average'

class AdminQualityAuditResource(Resource):
    """Quality audit for partners across the platform"""

    @jwt_required()
    def post(self):
        """Perform quality audit on all partners"""
        identity = get_jwt_identity()
        user = User.query.get(identity)

        if not user or user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403

        data = request.get_json() or {}
        organizer_id = data.get('organizer_id')

        # Get partners to audit
        query = Partner.query.filter_by(is_active=True)
        if organizer_id:
            query = query.filter_by(organizer_id=organizer_id)

        partners = query.all()

        # Audit each partner
        audit_results = {
            'total_audited': len(partners),
            'issues_found': [],
            'high_quality': [],
            'needs_improvement': [],
            'summary': {}
        }

        for partner in partners:
            validation = partner_assistant.validate_partner_data({
                'company_name': partner.company_name,
                'company_description': partner.company_description,
                'website_url': partner.website_url,
                'contact_email': partner.contact_email,
                'contact_person': partner.contact_person,
                'logo_url': partner.logo_url
            })

            quality_score = 100
            if validation['errors']:
                quality_score -= len(validation['errors']) * 30
            if validation['warnings']:
                quality_score -= len(validation['warnings']) * 15
            if validation['suggestions']:
                quality_score -= len(validation['suggestions']) * 10

            partner_audit = {
                'partner_id': partner.id,
                'partner_name': partner.company_name,
                'organizer_name': partner.organizer.company_name if partner.organizer else None,
                'quality_score': max(0, quality_score),
                'issues': validation['errors'] + validation['warnings'],
                'suggestions': validation['suggestions']
            }

            if quality_score >= 80:
                audit_results['high_quality'].append(partner_audit)
            elif quality_score < 60:
                audit_results['needs_improvement'].append(partner_audit)
                audit_results['issues_found'].append(partner_audit)

        # Generate summary
        audit_results['summary'] = {
            'high_quality_count': len(audit_results['high_quality']),
            'needs_improvement_count': len(audit_results['needs_improvement']),
            'avg_quality_score': round(
                sum(p['quality_score'] for p in audit_results['high_quality'] + audit_results['needs_improvement']) /
                len(partners), 2
            ) if partners else 0
        }

        return {
            "action": "quality_audit_complete",
            "audit_results": audit_results,
            "admin_actions": {
                "notify_organizers": "POST /admin/partners/ai/notify-quality-issues",
                "bulk_enhance": "POST /admin/partners/ai/bulk-enhance",
                "export_report": "GET /admin/partners/ai/audit-report"
            }
        }, 200

class AdminPlatformTrendsResource(Resource):
    """Platform-wide partnership trends and analytics"""

    @jwt_required()
    def get(self):
        """Get comprehensive platform trends"""
        identity = get_jwt_identity()
        user = User.query.get(identity)

        if not user or user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403

        # Analyze trends for each organizer
        organizers = Organizer.query.all()

        organizer_trends = []
        for organizer in organizers:
            try:
                trends = partner_assistant.identify_partnership_trends(organizer.id)
                organizer_trends.append({
                    'organizer_id': organizer.id,
                    'organizer_name': organizer.company_name,
                    'trends': trends
                })
            except Exception as e:
                logger.error(f"Error analyzing trends for organizer {organizer.id}: {e}")

        # Platform-wide aggregation
        platform_trends = self._aggregate_platform_trends(organizer_trends)

        return {
            "action": "platform_trends_analyzed",
            "platform_trends": platform_trends,
            "organizer_trends": organizer_trends,
            "admin_actions": {
                "deep_dive": "GET /admin/partners/ai/deep-analysis",
                "export_report": "GET /admin/partners/ai/trends-report",
                "comparative_analysis": "GET /admin/partners/ai/comparative-analysis"
            }
        }, 200

    def _aggregate_platform_trends(self, organizer_trends: list) -> Dict:
        """Aggregate trends across all organizers"""
        if not organizer_trends:
            return {"message": "No trend data available"}

        total_partners = sum(t['trends']['trends']['total_partners'] for t in organizer_trends)
        total_collabs = sum(t['trends']['trends']['active_collaborations'] for t in organizer_trends)

        avg_growth = sum(
            t['trends']['trends']['partner_growth_rate'] for t in organizer_trends
        ) / len(organizer_trends)

        avg_contribution = sum(
            t['trends']['trends']['avg_contribution_score_recent'] for t in organizer_trends
        ) / len(organizer_trends)

        return {
            'total_platform_partners': total_partners,
            'total_platform_collaborations': total_collabs,
            'avg_organizer_growth_rate': round(avg_growth, 2),
            'platform_avg_contribution_score': round(avg_contribution, 2),
            'active_organizers': len(organizer_trends),
            'health_assessment': (
                'thriving' if avg_contribution > 0.7 else
                'healthy' if avg_contribution > 0.5 else
                'needs_attention'
            )
        }

class AdminBulkAnalysisResource(Resource):
    """Bulk analysis for entire platform"""

    @jwt_required()
    def post(self):
        """Analyze all partners across the platform"""
        identity = get_jwt_identity()
        user = User.query.get(identity)

        if not user or user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403

        data = request.get_json() or {}
        organizer_id = data.get('organizer_id')

        # Get all organizers or specific one
        if organizer_id:
            organizers = [Organizer.query.get(organizer_id)]
            if not organizers[0]:
                return {"message": "Organizer not found"}, 404
        else:
            organizers = Organizer.query.all()

        platform_analysis = {
            'total_organizers_analyzed': len(organizers),
            'organizer_analyses': [],
            'platform_summary': {
                'total_partners': 0,
                'total_high_performers': 0,
                'total_needs_attention': 0,
                'platform_avg_performance': 0
            }
        }

        all_performances = []

        for organizer in organizers:
            try:
                analysis = partner_assistant.bulk_analyze_partners(organizer.id)
                platform_analysis['organizer_analyses'].append({
                    'organizer_id': organizer.id,
                    'organizer_name': organizer.company_name,
                    'analysis': analysis
                })

                # Aggregate for platform summary
                platform_analysis['platform_summary']['total_partners'] += analysis.get('total_partners', 0)
                platform_analysis['platform_summary']['total_high_performers'] += len(analysis.get('high_performers', []))
                platform_analysis['platform_summary']['total_needs_attention'] += len(analysis.get('needs_attention', []))

                if 'summary' in analysis and 'average_performance' in analysis['summary']:
                    all_performances.append(analysis['summary']['average_performance'])

            except Exception as e:
                logger.error(f"Error analyzing organizer {organizer.id}: {e}")

        # Calculate platform average
        if all_performances:
            platform_analysis['platform_summary']['platform_avg_performance'] = round(
                sum(all_performances) / len(all_performances), 2
            )

        return {
            "action": "bulk_analysis_complete",
            "analysis": platform_analysis,
            "admin_actions": {
                "address_low_performers": "POST /admin/partners/ai/optimize-low-performers",
                "export_report": "GET /admin/partners/ai/bulk-analysis-report",
                "notify_organizers": "POST /admin/partners/ai/notify-analysis"
            }
        }, 200

class AdminCollaborationOptimizationResource(Resource):
    """Optimize collaboration across the platform"""

    @jwt_required()
    def post(self, collaboration_id=None):
        """Optimize specific or all low-performing collaborations"""
        identity = get_jwt_identity()
        user = User.query.get(identity)

        if not user or user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403

        if collaboration_id:
            # Optimize specific collaboration
            collab = EventCollaboration.query.get(collaboration_id)
            if not collab:
                return {"message": "Collaboration not found"}, 404

            optimization = partner_assistant.optimize_collaboration(collaboration_id)

            return {
                "action": "collaboration_optimized",
                "collaboration_id": collaboration_id,
                "optimization": optimization
            }, 200
        else:
            # Bulk optimize low-performing collaborations
            low_performers = EventCollaboration.query.filter(
                EventCollaboration.is_active == True,
                EventCollaboration.contribution_score < 0.4
            ).all()

            optimizations = []
            for collab in low_performers[:20]:  # Limit to prevent timeout
                try:
                    opt = partner_assistant.optimize_collaboration(collab.id)
                    if opt:
                        optimizations.append({
                            'collaboration_id': collab.id,
                            'partner_name': collab.partner.company_name if collab.partner else None,
                            'event_name': collab.event.name if collab.event else None,
                            'optimization': opt
                        })
                except Exception as e:
                    logger.error(f"Error optimizing collaboration {collab.id}: {e}")

            return {
                "action": "bulk_optimization_complete",
                "total_low_performers": len(low_performers),
                "optimizations_generated": len(optimizations),
                "optimizations": optimizations,
                "admin_actions": {
                    "notify_organizers": "POST /admin/partners/ai/notify-optimizations",
                    "export_report": "GET /admin/partners/ai/optimization-report"
                }
            }, 200

def register_admin_partner_resources(api):
    """Register admin partner resources with Flask-RESTful API."""

    # Core admin overview
    api.add_resource(
        AdminPartnerOverviewResource,
        '/api/admin/partners',
        '/api/admin/partners/<int:entity_id>',
        '/api/admin/partners/collaborations',
        '/api/admin/partners/collaborations/event/<int:entity_id>',
        '/api/admin/partners/recent',
        '/api/admin/partners/inactive',
        '/api/admin/partners/analytics'
    )

    # Admin AI assistance endpoints
    api.add_resource(
        AdminPartnerAIAssistResource,
        '/api/admin/partners/ai/assist'
    )

    api.add_resource(
        AdminPartnerAnalysisResource,
        '/api/admin/partners/<int:partner_id>/ai/analyze'
    )

    api.add_resource(
        AdminQualityAuditResource,
        '/api/admin/partners/ai/quality-audit'
    )

    api.add_resource(
        AdminPlatformTrendsResource,
        '/api/admin/partners/ai/platform-trends'
    )

    api.add_resource(
        AdminBulkAnalysisResource,
        '/api/admin/partners/ai/bulk-analyze-all'
    )

    api.add_resource(
        AdminCollaborationOptimizationResource,
        '/api/admin/partners/ai/optimize-collaborations',
        '/api/admin/partners/ai/optimize-collaborations/<int:collaboration_id>'
    )
