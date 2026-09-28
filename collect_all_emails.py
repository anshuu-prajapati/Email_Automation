#!/usr/bin/env python3
"""
Collect emails for multiple Indian tech companies
Builds database with verified emails - completely FREE!

Usage:
    python collect_all_emails.py

Result:
    - verified_emails.csv - All verified emails
    - minihunter.db - Local database with all data
    - Report: Companies, emails found, valid emails
"""

import csv
import time
import logging
from typing import List, Dict, Set
from minihunter.free_sources import FreeEmailSources
from minihunter import MiniHunterAPI

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger("collect_emails")

# ════════════════════════════════════════════════════════════════════════════
#  INDIAN TECH COMPANIES TO COLLECT
# ════════════════════════════════════════════════════════════════════════════

# Add your companies here!
COMPANIES = [
    # Fintech
    {"name": "Spyne", "domain": "spyne.ai", "industry": "Computer Vision & AutoTech"},    # Add more companies below:
    # {"name": "Company Name", "domain": "company.com", "industry": "category"},
]


# ════════════════════════════════════════════════════════════════════════════
#  COLLECTOR CLASS
# ════════════════════════════════════════════════════════════════════════════

class EmailCollectorDB:
    """Collect emails for multiple companies and build database"""

    def __init__(self, db_path="minihunter.db"):
        self.free = FreeEmailSources()
        self.minihunter = MiniHunterAPI(db_path)
        self.results = []
        self.stats = {
            "companies_processed": 0,
            "total_potential": 0,
            "total_valid": 0,
            "companies_with_emails": 0,
        }

    def collect_for_company(self, company: Dict) -> Dict:
        """
        Collect and verify emails for one company

        Returns:
            {
                "company": "BharatPe",
                "domain": "bharatpe.com",
                "industry": "fintech",
                "potential": 12,
                "valid": 5,
                "emails": ["hr@bharatpe.com", ...]
            }
        """
        name = company['name']
        domain = company['domain']
        industry = company.get('industry', 'unknown')

        log.info(f"{'='*70}")
        log.info(f"Processing: {name} ({domain})")
        log.info(f"{'='*70}")

        try:
            # Step 1: Collect from free sources
            log.info("Step 1/3: Collecting from free sources...")
            all_emails = self.free.all_emails_combined(name, domain)

            if not all_emails:
                log.warning(f"  ⚠ No emails found from free sources")
                return {
                    "company": name,
                    "domain": domain,
                    "industry": industry,
                    "potential": 0,
                    "valid": 0,
                    "emails": []
                }

            log.info(f"  ✓ Found {len(all_emails)} potential emails")
            self.stats["total_potential"] += len(all_emails)

            # Step 2: Verify with SMTP
            log.info("Step 2/3: Verifying emails with SMTP...")
            results = self.minihunter.email_verifier(list(all_emails))

            valid = [r for r in results if r['status'] == 'valid']
            log.info(f"  ✓ Verified {len(valid)} valid emails")

            # Step 3: Save to database
            log.info("Step 3/3: Saving to database...")
            company_id = self.minihunter.db.add_company(name, domain, industry=industry)

            valid_emails = []
            for r in valid:
                self.minihunter.db.add_email(
                    company_id,
                    r['email'],
                    status=r['status'],
                    confidence=r['confidence'],
                    source='free'
                )
                valid_emails.append(r['email'])
                log.info(f"    • {r['email']}")

            self.stats["total_valid"] += len(valid)
            if valid:
                self.stats["companies_with_emails"] += 1

            result = {
                "company": name,
                "domain": domain,
                "industry": industry,
                "potential": len(all_emails),
                "valid": len(valid),
                "emails": valid_emails
            }

            self.results.append(result)

            log.info(f"\n✓ Complete: {len(valid)} valid emails for {name}")
            return result

        except Exception as e:
            log.error(f"✗ Error processing {name}: {str(e)}")
            return {
                "company": name,
                "domain": domain,
                "industry": industry,
                "potential": 0,
                "valid": 0,
                "emails": [],
                "error": str(e)
            }

    def collect_all(self, companies: List[Dict]) -> List[Dict]:
        """Collect for multiple companies"""
        log.info("\n")
        log.info("╔" + "="*68 + "╗")
        log.info("║  Starting Email Collection for Indian Tech Companies       ║")
        log.info("║  Cost: $0 (using free sources + MiniHunter verification)  ║")
        log.info("╚" + "="*68 + "╝")
        log.info("\n")

        start_time = time.time()

        for i, company in enumerate(companies, 1):
            log.info(f"\n[{i}/{len(companies)}]")
            self.collect_for_company(company)

            # Be polite to servers
            time.sleep(0.5)

        elapsed = time.time() - start_time
        self.stats["companies_processed"] = len(companies)
        self.stats["time_seconds"] = elapsed

        return self.results

    def export_csv(self, filename="verified_emails.csv") -> str:
        """Export all verified emails to CSV"""
        log.info(f"\nExporting to {filename}...")

        rows = []
        for result in self.results:
            if result['valid'] > 0:
                for email in result['emails']:
                    rows.append({
                        'email': email,
                        'company': result['company'],
                        'domain': result['domain'],
                        'industry': result.get('industry', 'unknown'),
                        'status': 'valid',
                        'source': 'free'
                    })

        if not rows:
            log.warning("No emails to export")
            return None

        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['email', 'company', 'domain', 'industry', 'status', 'source'])
                writer.writeheader()
                writer.writerows(rows)

            log.info(f"✓ Exported {len(rows)} emails to {filename}")
            return filename
        except Exception as e:
            log.error(f"✗ Error exporting: {str(e)}")
            return None

    def print_report(self):
        """Print summary report"""
        log.info("\n")
        log.info("╔" + "="*68 + "╗")
        log.info("║                    COLLECTION COMPLETE                      ║")
        log.info("╚" + "="*68 + "╝")
        log.info("\n")

        elapsed = self.stats.get('time_seconds', 0)
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)

        log.info("📊 STATISTICS")
        log.info("-" * 70)
        log.info(f"  Companies processed:      {self.stats['companies_processed']}")
        log.info(f"  Total potential emails:   {self.stats['total_potential']}")
        log.info(f"  Total valid emails:       {self.stats['total_valid']}")
        log.info(f"  Companies with emails:    {self.stats['companies_with_emails']}")

        if self.stats['total_potential'] > 0:
            coverage = (self.stats['total_valid'] / self.stats['total_potential']) * 100
            log.info(f"  Coverage:                 {coverage:.1f}%")

        log.info(f"  Time taken:               {minutes}m {seconds}s")
        log.info("")

        # Compare with Hunter
        hunter_cost = self.stats['total_valid'] * 0.02 + 99
        log.info("💰 COST COMPARISON")
        log.info("-" * 70)
        log.info(f"  Hunter.io would cost:     ${hunter_cost:.2f}")
        log.info(f"  MiniHunter costs:         $0.00 (FREE!)")
        log.info(f"  You save:                 ${hunter_cost:.2f}")
        log.info("")

        # Per company stats
        if self.results:
            log.info("📍 PER COMPANY BREAKDOWN")
            log.info("-" * 70)
            log.info(f"{'Company':<25} {'Domain':<20} {'Potential':<10} {'Valid':<10}")
            log.info("-" * 70)

            for result in self.results:
                company = result['company'][:24]
                domain = result['domain'][:19]
                potential = result['potential']
                valid = result['valid']
                log.info(f"{company:<25} {domain:<20} {potential:<10} {valid:<10}")

            log.info("")

        log.info("✅ FILES CREATED")
        log.info("-" * 70)
        log.info("  • verified_emails.csv      - All verified emails")
        log.info("  • minihunter.db            - Local database")
        log.info("")

        log.info("🚀 NEXT STEPS")
        log.info("-" * 70)
        log.info("  1. Use verified_emails.csv with your outreach automation")
        log.info("  2. Add more companies to COMPANIES list and run again")
        log.info("  3. Build up your email database (completely FREE!)")
        log.info("")

    def close(self):
        """Close database"""
        self.minihunter.close()


# ════════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    """Main entry point"""
    collector = EmailCollectorDB()

    try:
        # Collect for all companies
        collector.collect_all(COMPANIES)

        # Export to CSV
        csv_file = collector.export_csv("verified_emails.csv")

        # Print report
        collector.print_report()

        if csv_file:
            print(f"\n✓ SUCCESS! Emails saved to: {csv_file}")
            print(f"✓ Database saved to: minihunter.db")
            print(f"\nYou can now use verified_emails.csv with your automation!")

    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted by user")
    except Exception as e:
        log.error(f"Fatal error: {str(e)}", exc_info=True)
    finally:
        collector.close()


if __name__ == "__main__":
    main()
