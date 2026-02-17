console.log("This is the entry point of the Rust or Bust! app.");import { app, BrowserWindow} from 'electron';


const createWindow = () => {
    const win = new BrowserWindow( {
        width: 800,
        height: 600,
    })
    win.loadFile('index.html');
}

app.whenReady().then(() => {
    createWindow();
    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    })
})


app.on('window-all-closed', () => {
    app.quit();
})