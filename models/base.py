# """
# Base database configuration and shared tables
# This file contains:
# - SQLAlchemy instance
# - Association tables (many-to-many relationships)
# """
# from flask_sqlalchemy import SQLAlchemy

# # Initialize SQLAlchemy instance
# # This will be imported by all model files
# db = SQLAlchemy()

# # ===== ASSOCIATION TABLES =====
# # These tables handle many-to-many relationships

# # Event Likes: Users can like multiple events, events can be liked by multiple users
# event_likes = db.Table(
#     'event_likes',
#     db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
#     db.Column('event_id', db.Integer, db.ForeignKey('event.id'), primary_key=True)
# )