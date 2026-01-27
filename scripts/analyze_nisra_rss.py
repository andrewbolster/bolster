#!/usr/bin/env python
"""Analyze NISRA RSS feed to identify new datasets to add.

This script:
1. Fetches the latest NISRA RSS feed entries
2. Compares against existing implemented modules
3. Identifies gaps and suggests new datasets to add
"""

from datetime import datetime, timedelta
from collections import Counter
from bolster.utils.rss import get_nisra_statistics_feed, filter_entries

# Known implemented NISRA modules (from README.md coverage table)
IMPLEMENTED = {
    'labour market': 'nisra.labour_market',
    'deaths': 'nisra.deaths',
    'births': 'nisra.births',
    'stillbirths': 'nisra.births',
    'marriages': 'nisra.marriages',
    'composite economic index': 'nisra.composite_index',
    'nicei': 'nisra.composite_index',
    'construction': 'nisra.construction_output',
    'index of services': 'nisra.economic_indicators',
    'index of production': 'nisra.economic_indicators',
    'population estimates': 'nisra.population',
    'migration': 'nisra.migration',
    'annual survey of hours': 'nisra.ashe',
    'earnings': 'nisra.ashe',
    'ashe': 'nisra.ashe',
    'individual wellbeing': 'RECENTLY_MERGED',
    'hotel occupancy': 'RECENTLY_MERGED',
    'civil partnerships': 'IN_PROGRESS',
}

def categorize_entry(title: str) -> tuple[str, str]:
    """Categorize an RSS entry by matching against known datasets.

    Returns:
        Tuple of (status, module_name) where status is:
        - IMPLEMENTED: Already has a module
        - RECENTLY_MERGED: Just merged to main
        - IN_PROGRESS: Feature branch exists
        - NEW: Not yet implemented
    """
    title_lower = title.lower()

    for keyword, module in IMPLEMENTED.items():
        if keyword in title_lower:
            return module if module in ['RECENTLY_MERGED', 'IN_PROGRESS'] else 'IMPLEMENTED', module

    return 'NEW', None


def main():
    print("=" * 80)
    print("NISRA RSS Feed Analysis - Dataset Gap Identification")
    print("=" * 80)
    print()

    # Fetch feed
    print("Fetching NISRA RSS feed...")
    feed = get_nisra_statistics_feed(order='recent')
    print(f"✓ Found {len(feed.entries)} total entries")
    print()

    # Filter for recent entries (last 6 months)
    cutoff = datetime.now() - timedelta(days=180)
    recent_entries = filter_entries(feed.entries, after_date=cutoff)
    print(f"✓ Found {len(recent_entries)} entries from last 6 months")
    print()

    # Categorize entries
    new_datasets = []
    implemented_counts = Counter()
    recently_merged = []
    in_progress = []

    for entry in recent_entries:
        status, module = categorize_entry(entry.title)

        if status == 'IMPLEMENTED':
            implemented_counts[module] += 1
        elif status == 'RECENTLY_MERGED':
            recently_merged.append(entry.title)
        elif status == 'IN_PROGRESS':
            in_progress.append(entry.title)
        elif status == 'NEW':
            new_datasets.append(entry)

    # Report: Already Implemented
    print("📊 ALREADY IMPLEMENTED (publications in last 6 months):")
    print("-" * 80)
    for module, count in implemented_counts.most_common():
        print(f"  {module:40s} {count:3d} publications")
    print()

    # Report: Recently Merged
    if recently_merged:
        print("✅ RECENTLY MERGED TO MAIN:")
        print("-" * 80)
        for title in set(recently_merged):
            print(f"  • {title}")
        print()

    # Report: In Progress
    if in_progress:
        print("🚧 IN PROGRESS (feature branch exists):")
        print("-" * 80)
        for title in set(in_progress):
            print(f"  • {title}")
        print()

    # Report: New Opportunities
    print("🆕 NEW DATASET OPPORTUNITIES (not yet implemented):")
    print("-" * 80)

    if not new_datasets:
        print("  No new datasets identified - great coverage!")
    else:
        # Group by title keywords to identify unique datasets
        dataset_types = Counter()
        examples = {}

        for entry in new_datasets:
            # Extract key terms from title
            title_lower = entry.title.lower()

            # Common patterns to identify dataset types
            if 'waiting times' in title_lower or 'waiting list' in title_lower:
                dataset_types['Health Waiting Times/Lists'] += 1
                if 'Health Waiting Times/Lists' not in examples:
                    examples['Health Waiting Times/Lists'] = entry
            elif 'cancer' in title_lower:
                dataset_types['Cancer Statistics'] += 1
                if 'Cancer Statistics' not in examples:
                    examples['Cancer Statistics'] = entry
            elif 'road traffic' in title_lower or 'collisions' in title_lower:
                dataset_types['Road Traffic Collisions'] += 1
                if 'Road Traffic Collisions' not in examples:
                    examples['Road Traffic Collisions'] = entry
            elif 'security situation' in title_lower:
                dataset_types['Security Situation Statistics'] += 1
                if 'Security Situation Statistics' not in examples:
                    examples['Security Situation Statistics'] = entry
            elif 'dva' in title_lower or 'driver' in title_lower:
                dataset_types['DVA Statistics'] += 1
                if 'DVA Statistics' not in examples:
                    examples['DVA Statistics'] = entry
            elif 'tourism' in title_lower:
                dataset_types['Tourism Statistics'] += 1
                if 'Tourism Statistics' not in examples:
                    examples['Tourism Statistics'] = entry
            elif 'housing' in title_lower or 'house price' in title_lower:
                dataset_types['Housing/House Prices'] += 1
                if 'Housing/House Prices' not in examples:
                    examples['Housing/House Prices'] = entry
            elif 'trade' in title_lower or 'export' in title_lower or 'import' in title_lower:
                dataset_types['Trade Statistics'] += 1
                if 'Trade Statistics' not in examples:
                    examples['Trade Statistics'] = entry
            elif 'gdp' in title_lower or 'economic accounts' in title_lower:
                dataset_types['GDP/Economic Accounts'] += 1
                if 'GDP/Economic Accounts' not in examples:
                    examples['GDP/Economic Accounts'] = entry
            else:
                # Misc/other
                dataset_types['Other/Misc'] += 1

        for dataset_type, count in dataset_types.most_common():
            if dataset_type == 'Other/Misc':
                continue

            print(f"\n  {dataset_type}")
            print(f"    Publications (last 6 mo): {count}")

            if dataset_type in examples:
                example = examples[dataset_type]
                pub_date = example.published.strftime('%Y-%m-%d') if example.published else 'Unknown'
                print(f"    Example: [{pub_date}] {example.title}")
                print(f"    URL: {example.link}")

    print()
    print("=" * 80)
    print("💡 RECOMMENDATIONS:")
    print("=" * 80)

    # Provide recommendations based on publication frequency
    if dataset_types:
        top_opportunities = [
            (name, count)
            for name, count in dataset_types.most_common(5)
            if name != 'Other/Misc' and count >= 2
        ]

        if top_opportunities:
            print("\nHighest priority (frequent publications):")
            for name, count in top_opportunities:
                print(f"  • {name} ({count} publications in 6 months)")

        print("\n📋 Next steps:")
        print("  1. Review the RSS feed entries above")
        print("  2. Check if data is available as structured files (Excel/CSV)")
        print("  3. Assess if data fits the NISRA module pattern (mother page + Excel files)")
        print("  4. Create module following patterns in src/bolster/data_sources/nisra/README.md")
    else:
        print("\n  ✓ All major NISRA datasets are already implemented!")
        print("  ✓ Consider monitoring the RSS feed for new dataset types")

    print()


if __name__ == '__main__':
    main()
