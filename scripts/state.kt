package com.example.myapp

import androidx.compose.runtime.*
import androidx.compose.material3.*
import androidx.compose.foundation.layout.*

@Composable
fun CounterScreen() {
    // Observable state variables
    var count by remember { mutableStateOf(0) }
    var isEnabled by remember { mutableStateOf(true) }
    val title = "Counter App"  // Immutable
    
    Column {
        Text(text = title)
        Text(text = "Count: $count")
        
        Button(
            onClick = { 
                count++  // State update
                count = count + 1  // Another state update
            },
            enabled = isEnabled
        ) {
            Text("Increment")
        }
        
        Button(onClick = { isEnabled = !isEnabled }) {  // State update
            Text("Toggle")
        }
    }
}

class ViewModel {
    private val _uiState = MutableStateFlow<UiState>(UiState.Loading)
    val uiState: StateFlow<UiState> = _uiState
    
    var errorMessage: String? = null  // Mutable
    val appName = "MyApp"  // Immutable
    
    fun updateState(newState: UiState) {
        _uiState.value = newState  // State update
    }
}

sealed class UiState {
    object Loading : UiState()
    data class Success(val data: String) : UiState()
}