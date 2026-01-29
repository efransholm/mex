import subprocess 

fileSunflower = "../sunflower/app/src/main/java/com/google/samples/apps/sunflower/compose"

resultSunflower = subprocess.run(
    ["lizard", "-l", "kotlin", fileSunflower],
    capture_output=True,
    text=True
)

print("Raw Lizard output for Sunflower:\n", resultSunflower.stdout)