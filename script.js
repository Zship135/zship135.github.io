// ===== Mobile Navigation Toggle =====
const hamburger = document.querySelector('.hamburger');
const navMenu = document.querySelector('.nav-menu');

hamburger.addEventListener('click', () => {
    hamburger.classList.toggle('active');
    navMenu.classList.toggle('active');
});

// Close mobile menu when clicking on a link
document.querySelectorAll('.nav-link').forEach(n => n.addEventListener('click', () => {
    hamburger.classList.remove('active');
    navMenu.classList.remove('active');
}));

// ===== Smooth Scrolling for Navigation Links =====
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    });
});

// ===== Navbar Background Change on Scroll =====
window.addEventListener('scroll', () => {
    const navbar = document.querySelector('.navbar');
    if (window.scrollY > 50) {
        navbar.style.background = 'rgba(255, 255, 255, 0.98)';
        navbar.style.boxShadow = '0 2px 20px rgba(0, 0, 0, 0.1)';
    } else {
        navbar.style.background = 'rgba(255, 255, 255, 0.95)';
        navbar.style.boxShadow = 'none';
    }
});

// ===== Scroll Animations =====
// Disabled scroll animations to prevent transparency issues with fixed hero background
// All sections now remain fully opaque at all times

// If you want to re-enable animations later, uncomment the code below:
/*
const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
};

const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('visible');
            entry.target.classList.remove('animate-in');
        }
    });
}, observerOptions);

// Observe all sections for scroll animations, but skip the hero
document.querySelectorAll('section:not(.hero)').forEach(section => {
    section.classList.add('animate-in');
    observer.observe(section);
});
*/

// ===== Typing Animation for Hero Title =====
class TypeWriter {
    constructor(txtElement, words, wait = 3000) {
        this.txtElement = txtElement;
        this.words = words;
        this.txt = '';
        this.wordIndex = 0;
        this.wait = parseInt(wait, 10);
        this.type();
        this.isDeleting = false;
    }

    type() {
        const current = this.wordIndex % this.words.length;
        const fullTxt = this.words[current];

        if (this.isDeleting) {
            this.txt = fullTxt.substring(0, this.txt.length - 1);
        } else {
            this.txt = fullTxt.substring(0, this.txt.length + 1);
        }

        // Add the blinking cursor and update content
        this.txtElement.innerHTML = `<span class="txt">${this.txt}</span>`;

        let typeSpeed = 100; // Slower typing for more realistic effect

        if (this.isDeleting) {
            typeSpeed /= 2; // Faster deleting
        }

        if (!this.isDeleting && this.txt === fullTxt) {
            typeSpeed = this.wait;
            this.isDeleting = true;
        } else if (this.isDeleting && this.txt === '') {
            this.isDeleting = false;
            this.wordIndex++;
            typeSpeed = 500;
        }

        setTimeout(() => this.type(), typeSpeed);
    }
}

// ===== Initialize Typing Animation =====
document.addEventListener('DOMContentLoaded', () => {
    const txtElement = document.querySelector('.hero-subtitle');
    const words = [
        'Computer Science and Math Student', 
        'Data Analyst', 
        'SQL Developer', 
        'Database Designer',
        'Business Intelligence Specialist'
    ];
    
    if (txtElement) {
        new TypeWriter(txtElement, words, 2000);
    }
});

// ===== Animated Counter for Stats =====
function animateCounters() {
    const counters = document.querySelectorAll('.stat-number');
    
    counters.forEach(counter => {
        const target = parseInt(counter.textContent);
        const increment = target / 200;
        let count = 0;
        
        const updateCounter = () => {
            if (count < target) {
                count += increment;
                counter.textContent = Math.ceil(count) + '+';
                requestAnimationFrame(updateCounter);
            } else {
                counter.textContent = target + '+';
            }
        };
        
        updateCounter();
    });
}

// ===== Stats Animation Observer =====
const statsObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            animateCounters();
            statsObserver.unobserve(entry.target);
        }
    });
}, { threshold: 0.5 });

const statsSection = document.querySelector('.about-stats');
if (statsSection) {
    statsObserver.observe(statsSection);
}

// ===== Project Card Hover Effects =====
document.querySelectorAll('.project-card').forEach(card => {
    card.addEventListener('mouseenter', function() {
        this.style.transform = 'translateY(-10px) scale(1.02)';
    });
    
    card.addEventListener('mouseleave', function() {
        this.style.transform = 'translateY(0) scale(1)';
    });
});

// ===== Floating Elements Animation =====
function animateFloatingElements() {
    const elements = document.querySelectorAll('.floating-element');
    
    elements.forEach((element, index) => {
        const speed = element.dataset.speed || 1;
        const offset = Date.now() * 0.002 * speed + index * 2;
        const y = Math.sin(offset) * 10;
        const x = Math.cos(offset * 0.5) * 5;
        
        element.style.transform = `translate(${x}px, ${y}px)`;
    });
    
    requestAnimationFrame(animateFloatingElements);
}

// Start floating animation
animateFloatingElements();

// ===== Form Handling =====
const contactForm = document.querySelector('.contact-form form');
if (contactForm) {
    contactForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        // Get form data
        const formData = new FormData(this);
        const name = this.querySelector('input[type="text"]').value;
        const email = this.querySelector('input[type="email"]').value;
        const message = this.querySelector('textarea').value;
        
        // Simple validation
        if (!name || !email || !message) {
            alert('Please fill in all fields.');
            return;
        }
        
        // Show success message (you can integrate with a real form service)
        alert('Thank you for your message! I\'ll get back to you soon.');
        this.reset();
    });
}

// ===== Skill Items Animation =====
const skillItems = document.querySelectorAll('.skill-item');
skillItems.forEach((item, index) => {
    item.style.animationDelay = `${index * 0.1}s`;
});

// ===== Tech Stack Items Animation =====
const techItems = document.querySelectorAll('.tech-item');
techItems.forEach((item, index) => {
    item.addEventListener('mouseenter', function() {
        this.style.transform = 'scale(1.1) rotate(5deg)';
    });
    
    item.addEventListener('mouseleave', function() {
        this.style.transform = 'scale(1) rotate(0deg)';
    });
});

// ===== Parallax Effect for Hero Section =====
// Hero section is now fixed, so we don't need parallax scrolling
// The fixed positioning creates the desired effect automatically

// ===== Loading Animation =====
window.addEventListener('load', () => {
    const loader = document.querySelector('.loading');
    if (loader) {
        setTimeout(() => {
            loader.classList.add('hidden');
            setTimeout(() => {
                loader.remove();
            }, 500);
        }, 1000);
    }
});

// ===== Active Navigation Link Highlighting =====
window.addEventListener('scroll', () => {
    const sections = document.querySelectorAll('section[id]');
    const navLinks = document.querySelectorAll('.nav-link');
    
    let current = '';
    
    sections.forEach(section => {
        const sectionTop = section.offsetTop;
        const sectionHeight = section.clientHeight;
        if (scrollY >= (sectionTop - 200)) {
            current = section.getAttribute('id');
        }
    });
    
    navLinks.forEach(link => {
        link.classList.remove('active');
        if (link.getAttribute('href') === `#${current}`) {
            link.classList.add('active');
        }
    });
});

// ===== Smooth Page Transitions =====
document.addEventListener('DOMContentLoaded', function() {
    // Add fade-in animation to the body
    document.body.style.opacity = '0';
    document.body.style.transition = 'opacity 0.5s ease-in-out';
    
    setTimeout(() => {
        document.body.style.opacity = '1';
    }, 100);
});

// ===== Keyboard Navigation =====
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        // Close mobile menu if open
        hamburger.classList.remove('active');
        navMenu.classList.remove('active');
    }
});

// ===== Performance Optimization =====
// Throttle scroll events
function throttle(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Apply throttling to scroll events
const throttledScroll = throttle(() => {
    // Your scroll handling code here
}, 16); // ~60fps

window.addEventListener('scroll', throttledScroll);

// ===== Accessibility Improvements =====
// Focus management for mobile menu
const focusableElements = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

hamburger.addEventListener('click', () => {
    if (navMenu.classList.contains('active')) {
        // Focus first nav link when menu opens
        const firstFocusableElement = navMenu.querySelector(focusableElements);
        if (firstFocusableElement) {
            firstFocusableElement.focus();
        }
    }
});

// ===== Reduced Motion Support =====
const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

if (prefersReducedMotion.matches) {
    // Disable animations for users who prefer reduced motion
    document.querySelectorAll('*').forEach(el => {
        el.style.animationDuration = '0.01ms !important';
        el.style.animationIterationCount = '1 !important';
        el.style.transitionDuration = '0.01ms !important';
    });
}

console.log('🚀 Portfolio website loaded successfully!');

// ===== Stack Overflow Game =====
class StackOverflowGame {
    constructor() {
        this.stack = [];
        this.score = 0;
        this.level = 1;
        this.gameRunning = false;
        this.currentNumber = null;
        this.waitingForChoice = false;
        this.hasPopped = false; // Track if player has popped for current number
        this.maxStackHeight = 8; // Game ends when stack gets too tall
        this.moveCount = 0; // Track number of moves made
        this.nextRuleChange = 10 + Math.floor(Math.random() * 6); // 10-15 moves until rule change
        this.rules = [
            // Sum-based rules
            { name: "Keep stack sum even", check: (stack) => stack.length === 0 || stack.reduce((a, b) => a + b, 0) % 2 === 0 },
            { name: "Sum must be multiple of 3", check: (stack) => stack.length === 0 || stack.reduce((a, b) => a + b, 0) % 3 === 0 },
            { name: "Sum must be multiple of 4", check: (stack) => stack.length === 0 || stack.reduce((a, b) => a + b, 0) % 4 === 0 },
            { name: "Sum must be multiple of 5", check: (stack) => stack.length === 0 || stack.reduce((a, b) => a + b, 0) % 5 === 0 },
            { name: "Stack sum under 30", check: (stack) => {
                const sum = stack.length === 0 ? 0 : stack.reduce((a, b) => a + b, 0);
                return sum < 30;
            }},
            { name: "Stack sum under 50", check: (stack) => stack.length === 0 || stack.reduce((a, b) => a + b, 0) < 50 },
            { name: "Stack sum over 20", check: (stack) => stack.length === 0 || stack.reduce((a, b) => a + b, 0) > 20 },
            { name: "Sum between 10-40", check: (stack) => {
                if (stack.length === 0) return true;
                const sum = stack.reduce((a, b) => a + b, 0);
                return sum >= 10 && sum <= 40;
            }},
            
            // Number type rules
            { name: "Only odd numbers allowed", check: (stack) => stack.length === 0 || stack.every(num => num % 2 === 1) },
            { name: "Only even numbers allowed", check: (stack) => stack.length === 0 || stack.every(num => num % 2 === 0) },
            { name: "No multiples of 3", check: (stack) => stack.length === 0 || stack.every(num => num % 3 !== 0) },
            { name: "Only prime numbers", check: (stack) => {
                const isPrime = (n) => {
                    if (n < 2) return false;
                    for (let i = 2; i <= Math.sqrt(n); i++) {
                        if (n % i === 0) return false;
                    }
                    return true;
                };
                return stack.length === 0 || stack.every(num => isPrime(num));
            }},
            { name: "No single digits (>9)", check: (stack) => stack.length === 0 || stack.every(num => num > 9) },
            { name: "Only single digits (<10)", check: (stack) => stack.length === 0 || stack.every(num => num < 10) },
            
            // Order and pattern rules
            { name: "Stack must be ascending", check: (stack) => stack.length <= 1 || stack.every((val, i) => i === 0 || val >= stack[i-1]) },
            { name: "Stack must be descending", check: (stack) => stack.length <= 1 || stack.every((val, i) => i === 0 || val <= stack[i-1]) },
            { name: "Strictly ascending (no equals)", check: (stack) => stack.length <= 1 || stack.every((val, i) => i === 0 || val > stack[i-1]) },
            { name: "Strictly descending (no equals)", check: (stack) => stack.length <= 1 || stack.every((val, i) => i === 0 || val < stack[i-1]) },
            { name: "No consecutive duplicates", check: (stack) => {
                const result = stack.length <= 1 || stack.every((val, i) => i === 0 || val !== stack[i-1]);
                return result;
            }},
            { name: "All numbers must be unique", check: (stack) => stack.length === 0 || new Set(stack).size === stack.length },
            { name: "Alternating odd/even pattern", check: (stack) => {
                if (stack.length <= 1) return true;
                return stack.every((val, i) => i === 0 || (val % 2) !== (stack[i-1] % 2));
            }},
            
            // Size-based rules
            { name: "Max 3 items in stack", check: (stack) => stack.length <= 3 },
            { name: "Max 5 items in stack", check: (stack) => stack.length <= 5 },
            { name: "Max 6 items in stack", check: (stack) => stack.length <= 6 },
            { name: "At least 2 items required", check: (stack) => stack.length >= 2 },
            { name: "Exactly 4 items required", check: (stack) => stack.length === 0 || stack.length === 4 },
            
            // Range and comparison rules
            { name: "All numbers under 15", check: (stack) => stack.length === 0 || stack.every(num => num < 15) },
            { name: "All numbers over 5", check: (stack) => stack.length === 0 || stack.every(num => num > 5) },
            { name: "Numbers between 3-12", check: (stack) => stack.length === 0 || stack.every(num => num >= 3 && num <= 12) },
            { name: "Top number must be largest", check: (stack) => {
                if (stack.length <= 1) return true;
                const top = stack[stack.length - 1];
                return stack.every(num => num <= top);
            }},
            { name: "Bottom number must be smallest", check: (stack) => {
                if (stack.length <= 1) return true;
                const bottom = stack[0];
                return stack.every(num => num >= bottom);
            }},
            
            // Mathematical sequence rules
            { name: "Fibonacci sequence only", check: (stack) => {
                if (stack.length === 0) return true;
                const fibs = [1, 1, 2, 3, 5, 8, 13, 21, 34];
                return stack.every(num => fibs.includes(num));
            }},
            { name: "Perfect squares only", check: (stack) => {
                const isPerfectSquare = (n) => {
                    const sqrt = Math.sqrt(n);
                    return sqrt === Math.floor(sqrt);
                };
                return stack.length === 0 || stack.every(num => isPerfectSquare(num));
            }},
            { name: "Powers of 2 only", check: (stack) => {
                const isPowerOf2 = (n) => n > 0 && (n & (n - 1)) === 0;
                return stack.length === 0 || stack.every(num => isPowerOf2(num));
            }},
            
            // Advanced mathematical rules
            { name: "Average must be whole number", check: (stack) => {
                if (stack.length === 0) return true;
                const avg = stack.reduce((a, b) => a + b, 0) / stack.length;
                return avg === Math.floor(avg);
            }},
            { name: "No number appears twice", check: (stack) => stack.length === 0 || new Set(stack).size === stack.length },
            { name: "Sum of digits must be even", check: (stack) => {
                const sumDigits = (n) => n.toString().split('').reduce((sum, digit) => sum + parseInt(digit), 0);
                return stack.length === 0 || stack.every(num => sumDigits(num) % 2 === 0);
            }},
            { name: "Product must be even", check: (stack) => {
                if (stack.length === 0) return true;
                const product = stack.reduce((a, b) => a * b, 1);
                return product % 2 === 0;
            }},
            
            // Position-based rules
            { name: "Even positions = even numbers", check: (stack) => {
                return stack.length === 0 || stack.every((num, i) => (i % 2 === 0) === (num % 2 === 0));
            }},
            { name: "First and last must match", check: (stack) => {
                if (stack.length <= 1) return true;
                return stack[0] === stack[stack.length - 1];
            }},
            { name: "Middle number must be largest", check: (stack) => {
                if (stack.length <= 2) return true;
                const middle = Math.floor(stack.length / 2);
                const middleNum = stack[middle];
                return stack.every(num => num <= middleNum);
            }},
            
            // Creative rules
            { name: "No 7s allowed (unlucky!)", check: (stack) => stack.length === 0 || stack.every(num => num !== 7) },
            { name: "Must contain a 5", check: (stack) => stack.length === 0 || stack.includes(5) },
            { name: "Sum must be lucky (divisible by 7)", check: (stack) => stack.length === 0 || stack.reduce((a, b) => a + b, 0) % 7 === 0 },
            { name: "No teens (13-19)", check: (stack) => stack.length === 0 || stack.every(num => num < 13 || num > 19) },
            { name: "Binary numbers only (1,2,4,8,16...)", check: (stack) => {
                const isBinary = (n) => n > 0 && (n & (n - 1)) === 0;
                return stack.length === 0 || stack.every(num => isBinary(num));
            }}
        ];
        // Start with a random rule
        this.currentRule = this.rules[Math.floor(Math.random() * this.rules.length)];
        
        this.initializeGame();
    }

    initializeGame() {
        this.startBtn = document.getElementById('start-btn');
        this.restartBtn = document.getElementById('restart-btn');
        this.gameCanvas = document.getElementById('game-canvas');
        this.fallingNumbers = document.getElementById('falling-numbers');
        this.stackItems = document.getElementById('stack-items');
        this.scoreDisplay = document.getElementById('score');
        this.levelDisplay = document.getElementById('level');
        this.ruleDisplay = document.getElementById('current-rule');
        this.gameOver = document.getElementById('game-over');
        this.finalScore = document.getElementById('final-score');
        
        // Mobile control elements
        this.mobileControls = document.getElementById('mobile-controls');
        this.pushBtn = document.getElementById('push-btn');
        this.throwBtn = document.getElementById('throw-btn');
        this.popBtn = document.getElementById('pop-btn');

        this.startBtn.addEventListener('click', () => this.startGame());
        this.restartBtn.addEventListener('click', () => this.restartGame());
        document.addEventListener('keydown', (e) => this.handleKeyPress(e));
        
        // Mobile touch controls
        this.pushBtn.addEventListener('click', () => this.handleAction('push'));
        this.throwBtn.addEventListener('click', () => this.handleAction('throw'));
        this.popBtn.addEventListener('click', () => this.handleAction('pop'));
        
        // Detect if device is mobile and show controls accordingly
        this.detectMobile();

        this.updateDisplay();
    }

    // Detect if device is mobile and show appropriate controls
    detectMobile() {
        const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) 
                       || (window.innerWidth <= 768) 
                       || ('ontouchstart' in window)
                       || (navigator.maxTouchPoints && navigator.maxTouchPoints > 0);
        
        console.log(`Mobile detection: ${isMobile}`);
        console.log(`Screen width: ${window.innerWidth}`);
        console.log(`Touch support: ${'ontouchstart' in window}`);
        
        if (isMobile) {
            this.mobileControls.classList.remove('hidden');
            // Also show them whenever game starts on mobile
            this.isMobileDevice = true;
        } else {
            this.isMobileDevice = false;
        }
    }
    
    // Handle mobile button actions
    handleAction(action) {
        if (!this.gameRunning || !this.waitingForChoice || !this.currentNumber) {
            console.log(`Action blocked: gameRunning=${this.gameRunning}, waitingForChoice=${this.waitingForChoice}, currentNumber=${this.currentNumber}`);
            return;
        }
        
        console.log(`Mobile action: ${action}`);
        
        switch(action) {
            case 'push':
                this.pushToStack(this.currentNumber);
                this.waitingForChoice = false;
                // Move to next number
                if (this.gameRunning) {
                    setTimeout(() => this.presentNewNumber(), 500);
                }
                break;
            case 'throw':
                this.throwNumber();
                this.waitingForChoice = false;
                // Move to next number
                if (this.gameRunning) {
                    setTimeout(() => this.presentNewNumber(), 500);
                }
                break;
            case 'pop':
                if (!this.hasPopped && this.stack.length > 0) {
                    this.popFromStack();
                    // Don't move to next number - current number is still available
                } else {
                    console.log(`Pop blocked: hasPopped=${this.hasPopped}, stackLength=${this.stack.length}`);
                }
                break;
        }
        
        // Update mobile button states
        this.updateMobileButtons();
    }
    
    // Update mobile button states
    updateMobileButtons() {
        if (this.popBtn) {
            this.popBtn.disabled = this.hasPopped || this.stack.length === 0;
        }
    }

    startGame() {
        this.gameRunning = true;
        this.stack = [];
        this.score = 0;
        this.level = 1;
        this.hasPopped = false;
        this.moveCount = 0;
        this.nextRuleChange = 10 + Math.floor(Math.random() * 6); // 10-15 moves until first rule change
        // Randomize starting rule
        this.currentRule = this.rules[Math.floor(Math.random() * this.rules.length)];
        this.gameOver.classList.add('hidden');
        this.startBtn.style.display = 'none';
        
        // Always show mobile controls if on mobile device, or force show on smaller screens
        if (this.isMobileDevice || window.innerWidth <= 768) {
            this.mobileControls.classList.remove('hidden');
            console.log('Mobile controls shown for game start');
        }
        
        this.updateDisplay();
        this.updateMobileButtons(); // Initialize button states
        this.presentNewNumber();
    }

    restartGame() {
        this.startGame();
    }

    presentNewNumber() {
        if (!this.gameRunning) return;
        
        this.currentNumber = Math.floor(Math.random() * 9) + 1;
        this.waitingForChoice = true;
        this.hasPopped = false; // Reset pop tracking for new number
        
        // Clear any existing numbers and display the new one
        this.fallingNumbers.innerHTML = '';
        const numberElement = document.createElement('div');
        numberElement.className = 'current-number';
        numberElement.textContent = this.currentNumber;
        this.fallingNumbers.appendChild(numberElement);
        
        // Update mobile button states for new number
        this.updateMobileButtons();
        
        console.log(`New number presented: ${this.currentNumber}, waitingForChoice: ${this.waitingForChoice}`);
    }

    handleKeyPress(e) {
        if (!this.gameRunning || !this.waitingForChoice) return;
        
        e.preventDefault();
        
        if (e.key === 'ArrowLeft') {
            // PUSH - Add number to stack
            this.pushToStack(this.currentNumber);
            this.waitingForChoice = false;
            // Move to next number
            if (this.gameRunning) {
                setTimeout(() => this.presentNewNumber(), 500);
            }
        } else if (e.key === 'ArrowDown') {
            // THROW - Discard the number
            this.throwNumber();
            this.waitingForChoice = false;
            // Move to next number
            if (this.gameRunning) {
                setTimeout(() => this.presentNewNumber(), 500);
            }
        } else if (e.key === 'ArrowRight' && !this.hasPopped) {
            // POP - Remove top number from stack (only once per number)
            this.popFromStack();
            // Don't move to next number - current number is still available
        } else {
            return; // Ignore other keys or if already popped
        }
    }

    pushToStack(number = null) {
        const numberToPush = number || this.currentNumber;
        this.stack.push(numberToPush);
        this.score += 10;
        this.moveCount++; // Increment move counter
        this.playMoveSound('push'); // Play push sound
        this.updateDisplay();
        this.updateMobileButtons(); // Update mobile button states
        this.checkRuleChange(); // Check if rule should change
        this.checkRule();
        this.checkStackHeight(); // Check if stack is too tall
        this.checkLevelUp();
        this.clearCurrentNumber();
    }

    popFromStack() {
        if (this.stack.length > 0) {
            this.stack.pop();
            this.score += 3;  // Less points than pushing
            this.hasPopped = true; // Mark that we've popped for this number
            // Note: Pop doesn't increment moveCount or change rules since it doesn't advance to next number
            this.playMoveSound('pop'); // Play pop sound
            this.updateDisplay();
            this.updateMobileButtons(); // Update mobile button states
            this.checkRule();
            
            // Visual feedback that pop has been used
            const numberElement = document.querySelector('.current-number');
            if (numberElement) {
                numberElement.classList.add('pop-used');
            }
        }
        // Current number stays visible for another decision
    }

    throwNumber() {
        // No points for throwing away the number
        this.moveCount++; // Increment move counter for throw action too
        console.log(`Throw action - Move count: ${this.moveCount}`);
        this.playMoveSound('throw'); // Play throw sound
        this.checkRuleChange(); // Check if rule should change
        this.updateDisplay(); // Make sure display updates
        this.updateMobileButtons(); // Update mobile button states
        this.clearCurrentNumber();
    }

    clearCurrentNumber() {
        const numberElement = document.querySelector('.current-number');
        if (numberElement) {
            numberElement.classList.add('used');
            setTimeout(() => {
                this.fallingNumbers.innerHTML = '';
            }, 300);
        }
    }

    checkRule() {
        try {
            const ruleResult = this.currentRule.check(this.stack);
            console.log(`Rule check: "${this.currentRule.name}"`);
            console.log(`Stack: [${this.stack.join(', ')}]`);
            console.log(`Rule result: ${ruleResult}`);
            
            if (!ruleResult) {
                console.log(`❌ GAME ENDING - Rule violation: ${this.currentRule.name}`);
                console.log(`Final stack state: [${this.stack.join(', ')}]`);
                this.endGame();
            } else {
                console.log(`✅ Rule satisfied`);
            }
        } catch (error) {
            console.error(`Error checking rule "${this.currentRule.name}":`, error);
            // Don't end game on rule checking errors, just log them
        }
    }

    checkRuleChange() {
        if (this.moveCount >= this.nextRuleChange) {
            this.changeRule();
        }
    }

    changeRule() {
        console.log(`=== RULE CHANGE ATTEMPT ===`);
        console.log(`Current rule: "${this.currentRule.name}"`);
        console.log(`Current stack: ${JSON.stringify(this.stack)}`);
        
        // Find rules that the current stack already satisfies
        const compatibleRules = this.rules.filter(rule => {
            const isCompatible = rule !== this.currentRule && rule.check(this.stack);
            console.log(`Rule "${rule.name}": ${isCompatible ? 'COMPATIBLE' : 'NOT COMPATIBLE'}`);
            return isCompatible;
        });
        
        console.log(`Compatible rules found: ${compatibleRules.length}`);
        
        // If we have compatible rules, pick one randomly
        // If no compatible rules exist, keep the current rule and delay the change
        if (compatibleRules.length > 0) {
            const oldRule = this.currentRule.name;
            this.currentRule = compatibleRules[Math.floor(Math.random() * compatibleRules.length)];
            console.log(`Rule changed from "${oldRule}" to "${this.currentRule.name}"`);
            this.nextRuleChange = this.moveCount + 10 + Math.floor(Math.random() * 6); // Next change in 10-15 moves
            
            // Show rule change notification (no grace period needed!)
            this.showRuleChangeNotification();
        } else {
            // No compatible rules found, try again in a few moves
            console.log(`No compatible rules found, delaying rule change`);
            this.nextRuleChange = this.moveCount + 3 + Math.floor(Math.random() * 4); // Try again in 3-6 moves
        }
        
        console.log(`=== END RULE CHANGE ===`);
        this.updateDisplay();
    }

    showRuleChangeNotification() {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = 'rule-change-notification';
        notification.innerHTML = `
            <div class="notification-content">
                <h4>🔄 RULE CHANGED!</h4>
                <p>New rule: <strong>${this.currentRule.name}</strong></p>
                <p class="smart-text">Smart selection - already compatible!</p>
            </div>
        `;
        
        // Add to game canvas
        this.gameCanvas.appendChild(notification);
        
        // Add shake effect to rule display
        this.ruleDisplay.parentElement.classList.add('rule-shake');
        
        // Play a notification sound (if we had audio)
        this.playNotificationSound();
        
        // Remove notification after 3 seconds
        setTimeout(() => {
            if (notification.parentNode) {
                notification.classList.add('fade-out');
                setTimeout(() => {
                    if (notification.parentNode) {
                        notification.parentNode.removeChild(notification);
                    }
                }, 500);
            }
        }, 3000);
        
        // Remove shake effect
        setTimeout(() => {
            this.ruleDisplay.parentElement.classList.remove('rule-shake');
        }, 600);
    }

    playNotificationSound() {
        // Create a simple beep sound using Web Audio API
        try {
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioContext.createOscillator();
            const gainNode = audioContext.createGain();
            
            oscillator.connect(gainNode);
            gainNode.connect(audioContext.destination);
            
            oscillator.frequency.setValueAtTime(800, audioContext.currentTime);
            oscillator.frequency.setValueAtTime(600, audioContext.currentTime + 0.1);
            
            gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
            gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.3);
            
            oscillator.start(audioContext.currentTime);
            oscillator.stop(audioContext.currentTime + 0.3);
        } catch (e) {
            // If audio context fails, just continue silently
            console.log('Audio notification not available');
        }
    }

    playMoveSound(moveType) {
        // Create different sounds for each move type
        try {
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioContext.createOscillator();
            const gainNode = audioContext.createGain();
            
            oscillator.connect(gainNode);
            gainNode.connect(audioContext.destination);
            
            // Different sounds for different moves
            switch(moveType) {
                case 'push':
                    // Rising tone for push (adding to stack)
                    oscillator.frequency.setValueAtTime(300, audioContext.currentTime);
                    oscillator.frequency.linearRampToValueAtTime(500, audioContext.currentTime + 0.1);
                    gainNode.gain.setValueAtTime(0.2, audioContext.currentTime);
                    gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.15);
                    oscillator.start(audioContext.currentTime);
                    oscillator.stop(audioContext.currentTime + 0.15);
                    break;
                    
                case 'pop':
                    // Sharp quick blip for pop (removing from stack)
                    oscillator.frequency.setValueAtTime(700, audioContext.currentTime);
                    oscillator.frequency.exponentialRampToValueAtTime(400, audioContext.currentTime + 0.08);
                    gainNode.gain.setValueAtTime(0.25, audioContext.currentTime);
                    gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.1);
                    oscillator.start(audioContext.currentTime);
                    oscillator.stop(audioContext.currentTime + 0.1);
                    break;
                    
                case 'throw':
                    // Falling tone for throw (discarding)
                    oscillator.frequency.setValueAtTime(400, audioContext.currentTime);
                    oscillator.frequency.exponentialRampToValueAtTime(200, audioContext.currentTime + 0.2);
                    gainNode.gain.setValueAtTime(0.15, audioContext.currentTime);
                    gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.25);
                    oscillator.start(audioContext.currentTime);
                    oscillator.stop(audioContext.currentTime + 0.25);
                    break;
            }
        } catch (e) {
            // If audio context fails, just continue silently
            console.log('Audio for move not available');
        }
    }

    checkStackHeight() {
        if (this.stack.length > this.maxStackHeight) {
            this.endGame();
        }
    }

    checkLevelUp() {
        const newLevel = Math.floor(this.score / 100) + 1;
        if (newLevel > this.level) {
            this.level = newLevel;
            // Note: We no longer change rules based on level ups
            // Rules now change based on move count with proper notifications
            console.log(`Level up! New level: ${this.level}`);
        }
    }

    updateDisplay() {
        this.scoreDisplay.textContent = this.score;
        this.levelDisplay.textContent = this.level;
        
        // Simple rule display (no grace indicators needed)
        let ruleText = this.currentRule.name;
        
        // Debug: Track if rule display changed unexpectedly
        if (this.lastDisplayedRule && this.lastDisplayedRule !== this.currentRule.name) {
            console.log(`🚨 RULE CHANGED DETECTED IN DISPLAY: "${this.lastDisplayedRule}" → "${this.currentRule.name}"`);
        }
        this.lastDisplayedRule = this.currentRule.name;
        
        this.ruleDisplay.textContent = ruleText;

        // Update rule help text if it exists
        const ruleHelp = document.getElementById('rule-help');
        if (ruleHelp) {
            ruleHelp.textContent = this.currentRule.name;
        }

        // Update stack display
        this.stackItems.innerHTML = '';
        this.stack.forEach(number => {
            const item = document.createElement('div');
            item.className = 'stack-item';
            item.textContent = number;
            this.stackItems.appendChild(item);
        });

        // Update moves until next rule change (optional debug info)
        // You could display this if you want players to know when rules will change
        const movesLeft = this.nextRuleChange - this.moveCount;
        if (movesLeft <= 3) {
            // Hint that rule change is coming soon
            this.ruleDisplay.parentElement.classList.add('rule-warning');
        } else {
            this.ruleDisplay.parentElement.classList.remove('rule-warning');
        }
        
        // Update mobile button states
        this.updateMobileButtons();
    }

    endGame() {
        this.gameRunning = false;
        this.waitingForChoice = false;
        this.fallingNumbers.innerHTML = '';
        this.finalScore.textContent = this.score;
        this.gameOver.classList.remove('hidden');
        this.startBtn.style.display = 'inline-block';
        this.mobileControls.classList.add('hidden'); // Hide mobile controls when game ends
    }
}

// Initialize game when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('game-canvas')) {
        new StackOverflowGame();
    }
});
