from django.core.management.base import BaseCommand
from infrastructure.persistence.workspaces.models import WorkspaceCategory, SubCategory

class Command(BaseCommand):
    help = 'Populates initial workspace categories and subcategories'

    def handle(self, *args, **options):
        categories_with_subcategories = {
            "Animal Welfare": ["Rescue", "Adoption", "Rehabilitation", "Advocacy"],
            "Community": ["Youth Programs", "Senior Services", "Neighborhood Improvement", "Local Events"],
            "Childcare": ["Daycare", "Preschool", "After-School Programs", "Parent Support"],
            "Arts": ["Visual Arts", "Performing Arts", "Music", "Literature"],
            "Environment": ["Conservation", "Sustainability", "Recycling", "Education"],
            "Health Promotion": ["Fitness", "Nutrition", "Mental Health", "Wellness"],
            "Health Providers": ["Clinics", "Hospitals", "Mental Health Services", "Rehabilitation"],
            "Housing": ["Affordable Housing", "Homeless Services", "Tenant Advocacy", "Housing Rehabilitation"],
            "Microfinance": ["Small Business Loans", "Financial Literacy", "Savings Groups", "Entrepreneurship"],
            "Medical Research": ["Cancer Research", "Disease Research", "Clinical Trials", "Genetic Studies"],
            "Human Rights": ["Civil Rights", "Refugee Advocacy", "Women's Rights", "Legal Aid"],
            "Ancillary Funds": ["Grantmaking", "Scholarships", "Charitable Trusts", "Philanthropic Services"],
            "Benevolent Institutes": ["Charitable Giving", "Community Support", "Disaster Relief", "Welfare Services"],
            "Social Clubs": ["Hobby Groups", "Interest Clubs", "Community Gatherings", "Networking"],
            "Sports": ["Youth Sports", "Adult Leagues", "Fitness Programs", "Sports Development"],
            "Education": ["Primary Education", "Secondary Education", "Higher Education", "Vocational Training"],
            "Self-Help": ["Support Groups", "Recovery Programs", "Personal Development", "Peer Counseling"],
        }

        for category_name, subcategory_names in categories_with_subcategories.items():
            category, created = WorkspaceCategory.objects.get_or_create(name=category_name)
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created category: {category_name}'))
            else:
                self.stdout.write(self.style.SUCCESS(f'Category already exists: {category_name}'))

            for subcategory_name in subcategory_names:
                subcategory, created = SubCategory.objects.get_or_create(name=subcategory_name, category=category)
                if created:
                    self.stdout.write(self.style.SUCCESS(f'  Created subcategory: {subcategory_name}'))
                else:
                    self.stdout.write(self.style.SUCCESS(f'  Subcategory already exists: {subcategory_name}'))

        self.stdout.write(self.style.SUCCESS('Successfully populated workspace categories and subcategories'))
