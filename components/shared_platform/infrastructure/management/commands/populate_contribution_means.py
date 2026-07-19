from django.core.management.base import BaseCommand
from infrastructure.persistence.workspaces.models import ContributionMeans

class Command(BaseCommand):
    help = 'Populates initial contribution means'

    def handle(self, *args, **options):
        means_list = [
            {"name": "Funding", "description": "Support with money", "is_active": True},
            {"name": "Volunteering", "description": "Offer your time and skills", "is_active": True},
            {"name": "Talents", "description": "Share your unique talents", "is_active": True},
            {"name": "Projects", "description": "Contribute to specific projects", "is_active": True},
            {"name": "Mentorship", "description": "Guide and mentor others", "is_active": True},
            {"name": "Goods", "description": "Donate goods or materials", "is_active": True},
            {"name": "Services", "description": "Provide professional services", "is_active": True},
            {"name": "Advocacy", "description": "Advocate for our cause", "is_active": True},
            {"name": "Sponsorship", "description": "Sponsor a specific person, event, or activity", "is_active": True},
            {"name": "Event Hosting", "description": "Host or organize events to support the workspace", "is_active": True},
            {"name": "Fundraising", "description": "Lead or participate in fundraising campaigns", "is_active": True},
            {"name": "Awareness Raising", "description": "Help spread the word about our mission", "is_active": True},
            {"name": "Networking", "description": "Connect us with potential partners or supporters", "is_active": True},
            {"name": "Technical Support", "description": "Provide IT or technical help", "is_active": True},
            {"name": "Legal Support", "description": "Offer legal advice or services", "is_active": True},
            {"name": "Medical Support", "description": "Provide medical expertise or services", "is_active": True},
            {"name": "Educational Support", "description": "Teach, tutor, or provide educational resources", "is_active": True},
            {"name": "Transportation", "description": "Help with logistics or transport needs", "is_active": True},
            {"name": "Translation", "description": "Translate materials or interpret for events", "is_active": True},
            {"name": "Art & Design", "description": "Create art, graphics, or design materials", "is_active": True},
            {"name": "Photography & Video", "description": "Capture photos or videos for our work", "is_active": True},
            {"name": "Writing & Editing", "description": "Write or edit content for us", "is_active": True},
            {"name": "Social Media", "description": "Manage or promote us on social media", "is_active": True},
            {"name": "Grant Writing", "description": "Help write grant applications", "is_active": True},
            {"name": "Research", "description": "Conduct research to support our mission", "is_active": True},
            {"name": "Mentoring Youth", "description": "Mentor young people in our programs", "is_active": True},
            {"name": "Childcare", "description": "Provide childcare during events or programs", "is_active": True},
            {"name": "Food Donation", "description": "Donate food or organize food drives", "is_active": True},
            {"name": "Clothing Donation", "description": "Donate clothing or organize clothing drives", "is_active": True},
            {"name": "Book Donation", "description": "Donate books or educational materials", "is_active": True},
            {"name": "Facility Use", "description": "Offer space for meetings or events", "is_active": True},
            {"name": "Equipment Loan", "description": "Lend equipment or tools", "is_active": True},
            {"name": "Advisory", "description": "Serve on an advisory board or committee", "is_active": True},
            {"name": "Board Membership", "description": "Serve as a board member", "is_active": True},
            {"name": "Peer Support", "description": "Provide peer-to-peer support", "is_active": True},
            {"name": "Environmental Action", "description": "Participate in cleanups or green projects", "is_active": True},
            {"name": "Crafts & Handmade Goods", "description": "Make or donate handmade items", "is_active": True},
            {"name": "IT Infrastructure", "description": "Help set up or maintain IT systems", "is_active": True},
            {"name": "Data Analysis", "description": "Analyze data to improve our impact", "is_active": True},
            {"name": "Public Speaking", "description": "Speak at events or represent us publicly", "is_active": True},
            {"name": "Music & Performance", "description": "Perform or organize performances", "is_active": True},
            {"name": "Sports Coaching", "description": "Coach or organize sports activities", "is_active": True},
            {"name": "Health & Wellness", "description": "Lead wellness or fitness activities", "is_active": True},
            {"name": "Peer Counseling", "description": "Provide peer counseling or support groups", "is_active": True},
            {"name": "Emergency Response", "description": "Help in emergencies or disaster relief", "is_active": True},
            {"name": "Animal Care", "description": "Help care for animals or organize adoptions", "is_active": True},
            {"name": "Gardening & Urban Farming", "description": "Help with gardens or urban farms", "is_active": True},
            {"name": "Building & Repairs", "description": "Assist with construction or repairs", "is_active": True},
            {"name": "Advocacy Campaigns", "description": "Lead or join advocacy campaigns", "is_active": True},
            {"name": "Community Organizing", "description": "Organize community events or groups", "is_active": True},
            {"name": "Resource Sharing", "description": "Share resources or connect others", "is_active": True},
            {"name": "Other", "description": "Other ways to help not listed here", "is_active": True},
        ]

        for means_data in means_list:
            means, created = ContributionMeans.objects.get_or_create(
                name=means_data["name"],
                defaults={
                    "description": means_data["description"],
                    "is_active": means_data["is_active"]
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created contribution means: {means.name}'))
            else:
                self.stdout.write(self.style.SUCCESS(f'Contribution means already exists: {means.name}'))

        self.stdout.write(self.style.SUCCESS('Successfully populated contribution means')) 