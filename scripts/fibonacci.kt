fun printFactors(n: Int) {
    if (n < 1) return
    print("$n => ")
    (1..n / 2)
        .filter { n % it == 0 }
        .forEach { print("$it ") }
    println(n)
}
