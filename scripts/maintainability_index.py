import math

def calculate_maintainability_index(halstead_volume: float, cyclomatic_complexity: int, lines_of_code: int) -> float:
    '''
    Maintainability index calculation according to Microsoft (0-100) definition
    '''
    if halstead_volume == 0 or cyclomatic_complexity == 0 or lines_of_code == 0:
        return float('nan') 
    
    mi = 171 - 5.2 * math.log(halstead_volume) - 0.23 * cyclomatic_complexity - 16.2 * math.log(lines_of_code)
    return max(0, mi * 100 / 171)

if __name__ == "__main__":
    # Example usage
    halstead_volume = 1000.0
    cyclomatic_complexity = 10
    lines_of_code = 200
    
    mi = calculate_maintainability_index(halstead_volume, cyclomatic_complexity, lines_of_code)
    print(f"Maintainability Index: {mi:.2f}")
    
