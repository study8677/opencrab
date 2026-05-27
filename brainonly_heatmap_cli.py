"""命令行接口：查看brainonly热图"""

import argparse
from brainonly_heatmap import get_heatmap, get_blind_spots, get_recent_touches

def main():
    parser = argparse.ArgumentParser(description='Brainonly heatmap viewer')
    parser.add_argument('--recent', type=int, default=24, 
                       help='Show touches in last N hours (default: 24)')
    parser.add_argument('--blindspots', action='store_true',
                       help='Show blindspot functions')
    parser.add_argument('--all-functions', nargs='+',
                       help='List of all functions to check blindspots against')
    
    args = parser.parse_args()
    
    if args.blindspots and args.all_functions:
        blindspots = get_blind_spots(args.all_functions)
        print(f"Blindspot functions ({len(blindspots)}):")
        for func in sorted(blindspots):
            print(f"  - {func}")
    
    heatmap = get_recent_touches(args.recent)
    if heatmap:
        print(f"\nFunctions touched in last {args.recent} hours ({len(heatmap)}):")
        for func, count in sorted(heatmap.items(), key=lambda x: x[1], reverse=True):
            print(f"  {func}: {count}")
    else:
        print("No recent touches recorded")

if __name__ == '__main__':
    main()
