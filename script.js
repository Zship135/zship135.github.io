// Navigation functionality
document.addEventListener('DOMContentLoaded', function() {
    // Initialize background effects
    initializeBackground();
    
    // Initialize home section animations
    initializeHomeAnimations();
    
    // Smooth scrolling and section switching
    const navItems = document.querySelectorAll('.nav-item');
    const sections = document.querySelectorAll('.section');
    
    navItems.forEach(item => {
        item.addEventListener('click', function(e) {
            e.preventDefault();
            
            // Add typing effect to terminal
            addTypingEffect(this.dataset.command);
            
            // Get target section
            const targetId = this.getAttribute('href').substring(1);
            const targetSection = document.getElementById(targetId);
            
            // Hide all sections
            sections.forEach(section => {
                section.classList.remove('active');
            });
            
            // Show target section with delay for effect
            setTimeout(() => {
                if (targetSection) {
                    targetSection.classList.add('active');
                }
            }, 300);
            
            // Update active nav item
            navItems.forEach(nav => nav.classList.remove('active'));
            this.classList.add('active');
        });
    });
    
    // Terminal typing effect
    function addTypingEffect(command) {
        const terminalPrompt = document.querySelector('.terminal-prompt .command');
        const originalCommand = terminalPrompt.textContent;
        
        // Clear current command
        terminalPrompt.textContent = '';
        terminalPrompt.style.color = '#10b981';
        
        // Type new command
        let i = 0;
        const typeCommand = () => {
            if (i < command.length) {
                terminalPrompt.textContent += command.charAt(i);
                i++;
                setTimeout(typeCommand, 50);
            } else {
                // Revert to original after delay
                setTimeout(() => {
                    terminalPrompt.textContent = originalCommand;
                    terminalPrompt.style.color = '#f59e0b';
                }, 1500);
            }
        };
        
        setTimeout(typeCommand, 200);
    }
    
    // Terminal window controls
    const controls = document.querySelectorAll('.control');
    controls.forEach(control => {
        control.addEventListener('click', function() {
            const terminalNav = document.querySelector('.terminal-nav');
            
            if (this.classList.contains('minimize')) {
                terminalNav.style.transform = 'translateX(-50%) scale(0.8)';
                terminalNav.style.opacity = '0.3';
                setTimeout(() => {
                    terminalNav.style.transform = 'translateX(-50%) scale(1)';
                    terminalNav.style.opacity = '1';
                }, 1000);
            } else if (this.classList.contains('maximize')) {
                terminalNav.style.transform = 'translateX(-50%) scale(1.05)';
                setTimeout(() => {
                    terminalNav.style.transform = 'translateX(-50%) scale(1)';
                }, 300);
            } else if (this.classList.contains('close')) {
                terminalNav.style.transform = 'translateX(-50%) translateY(-20px)';
                terminalNav.style.opacity = '0';
                setTimeout(() => {
                    terminalNav.style.transform = 'translateX(-50%) translateY(0)';
                    terminalNav.style.opacity = '1';
                }, 1000);
            }
        });
    });
    
    // Glitch effect for terminal occasionally
    function addGlitchEffect() {
        const terminal = document.querySelector('.terminal-nav');
        
        setInterval(() => {
            if (Math.random() > 0.95) {
                terminal.style.filter = 'hue-rotate(90deg) contrast(1.2)';
                terminal.style.transform = 'translateX(-50%) translateX(2px)';
                
                setTimeout(() => {
                    terminal.style.filter = 'none';
                    terminal.style.transform = 'translateX(-50%)';
                }, 100);
            }
        }, 5000);
    }
    
    addGlitchEffect();
    
    // Home section animations
    function initializeHomeAnimations() {
        // Add click handlers to quick actions
        const actionItems = document.querySelectorAll('.action-item');
        actionItems.forEach((item, index) => {
            item.addEventListener('click', function() {
                const navItems = document.querySelectorAll('.nav-item');
                // Skip home (index 0) and click the corresponding nav item
                if (navItems[index + 1]) {
                    navItems[index + 1].click();
                }
            });
        });
        
        // Add typing effect to JSON output
        const jsonLines = document.querySelectorAll('.json-line');
        jsonLines.forEach((line, index) => {
            line.style.opacity = '0';
            setTimeout(() => {
                line.style.animation = 'typeIn 0.5s ease-in-out forwards';
            }, 5000 + (index * 200)); // Start after welcome message
        });
        
        // Add subtle animation to focus areas
        const focusItems = document.querySelectorAll('.focus-item');
        focusItems.forEach((item, index) => {
            item.style.opacity = '0';
            item.style.transform = 'translateY(10px)';
            setTimeout(() => {
                item.style.animation = 'typeIn 0.6s ease-in-out forwards';
            }, 6000 + (index * 300)); // Start after JSON animation
        });
    }
    
    // Background initialization function
    function initializeBackground() {
        const backgroundContainer = document.querySelector('.background-container');
        
        // Create circuit connections
        createCircuitConnections(backgroundContainer);
    }
    
    function createCircuitConnections(container) {
        function addConnection() {
            const connection = document.createElement('div');
            connection.className = 'connection-line';
            
            const isHorizontal = Math.random() > 0.5;
            
            if (isHorizontal) {
                connection.style.width = (100 + Math.random() * 200) + 'px';
                connection.style.height = '1px';
                connection.style.left = Math.random() * 80 + '%';
                connection.style.top = Math.random() * 100 + '%';
            } else {
                connection.style.width = '1px';
                connection.style.height = (100 + Math.random() * 200) + 'px';
                connection.style.left = Math.random() * 100 + '%';
                connection.style.top = Math.random() * 80 + '%';
                connection.style.background = 'linear-gradient(0deg, transparent, rgba(0, 255, 65, 0.2), transparent)';
            }
            
            connection.style.animationDelay = Math.random() * 6 + 's';
            connection.style.animationDuration = (4 + Math.random() * 4) + 's';
            
            container.appendChild(connection);
            
            // Remove connection after some time
            setTimeout(() => {
                if (container.contains(connection)) {
                    container.removeChild(connection);
                }
            }, 15000);
        }
        
        // Add connections periodically
        setInterval(addConnection, 4000);
        
        // Initial connections
        for (let i = 0; i < 3; i++) {
            setTimeout(addConnection, i * 2000);
        }
    }
    
    // Konami code easter egg for extra effects
    let konamiCode = [];
    const konamiSequence = [
        'ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown',
        'ArrowLeft', 'ArrowRight', 'ArrowLeft', 'ArrowRight',
        'KeyB', 'KeyA'
    ];
    
    document.addEventListener('keydown', function(e) {
        konamiCode.push(e.code);
        if (konamiCode.length > konamiSequence.length) {
            konamiCode.shift();
        }
        
        if (JSON.stringify(konamiCode) === JSON.stringify(konamiSequence)) {
            // Activate special effects
            document.body.style.animation = 'matrix-mode 2s ease-in-out';
            const terminal = document.querySelector('.terminal-nav');
            terminal.style.boxShadow = '0 0 30px #00ff41, inset 0 0 30px rgba(0,255,65,0.1)';
            
            setTimeout(() => {
                document.body.style.animation = '';
                terminal.style.boxShadow = '';
            }, 3000);
            
            konamiCode = [];
        }
    });
});

// CSS animation for matrix mode (injected via JS)
const matrixModeCSS = `
@keyframes matrix-mode {
    0% { filter: hue-rotate(0deg); }
    50% { filter: hue-rotate(120deg) brightness(1.2) contrast(1.5); }
    100% { filter: hue-rotate(0deg); }
}
`;

const style = document.createElement('style');
style.textContent = matrixModeCSS;
document.head.appendChild(style);
