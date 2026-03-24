package com.example.views_app

import android.os.Bundle
import android.widget.Button
import android.widget.ImageView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.activity.enableEdgeToEdge

class MainActivity : AppCompatActivity() {

    private var count = 0

    private lateinit var countText: TextView
    private lateinit var levelText: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_main)

        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main)) { v, insets ->
            val systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            v.setPadding(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom)
            insets
        }

        countText = findViewById(R.id.textCount)
        levelText = findViewById(R.id.textLevel)
        val button = findViewById<Button>(R.id.buttonTap)

        button.setOnClickListener {
            count++
            updateUI()
        }
    }

    private fun updateUI() {
        countText.text = "Count: $count"
        if (count > 5) {
            levelText.text = "High"
            levelText.setTextColor(ContextCompat.getColor(this, R.color.high_color))
        } else {
            levelText.text = "Low"
            levelText.setTextColor(ContextCompat.getColor(this, R.color.low_color))
        }
    }
}