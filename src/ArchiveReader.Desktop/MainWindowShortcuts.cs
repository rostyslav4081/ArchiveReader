using System.Windows;
using System.Windows.Input;
using System.Windows.Media.Imaging;

namespace ArchiveReader;
public partial class MainWindow
{
    async Task SaveEditedLine(bool verified=false)
    {
        if(current==null || LineList.SelectedItem is not LineItem line) return;
        var original=(line.Data["corrected"] ?? line.Data["text"])?.ToString() ?? "";
        if(!verified && original==LineText.Text) return;
        await Call("save_line",new(){["id"]=current.Id,["line"]=line.Index,["text"]=LineText.Text,["verified"]=verified});
        line.Data["corrected"]=LineText.Text; line.Data["verified"]=verified; LineList.Items.Refresh();
    }
    void NextUncertainLine()
    {
        var items=LineList.Items.Cast<LineItem>().ToList(); if(items.Count==0) { Status.Text=T("На сторінці немає рядків OCR."); return; }
        int start=LineList.SelectedIndex;
        for(int offset=1;offset<=items.Count;offset++)
        {
            int index=(start+offset)%items.Count; var data=items[index].Data;
            if(data["verified"]?.GetValue<bool>()==true) continue;
            OcrLines.IsExpanded=true; LineList.SelectedIndex=index; LineList.ScrollIntoView(items[index]); LineText.Focus(); LineText.SelectAll(); LineText.BringIntoView(); return;
        }
        Status.Text=T("Усі рядки цієї сторінки перевірені.");
    }
    void CenterSelectedLine()
    {
        if(Overlay.Children.Count==0) return;
        var shape=Overlay.Children[0];
        if(shape is System.Windows.FrameworkElement element)
        { double x=System.Windows.Controls.Canvas.GetLeft(element),y=System.Windows.Controls.Canvas.GetTop(element); ImageScroll.ScrollToHorizontalOffset(Math.Max(0,x*Zoom.Value-ImageScroll.ViewportWidth/2)); ImageScroll.ScrollToVerticalOffset(Math.Max(0,y*Zoom.Value-ImageScroll.ViewportHeight/2)); }
    }
    async void HandleShortcut(object sender,KeyEventArgs e)
    {
        if(loading || busy || switching) return;
        bool control=Keyboard.Modifiers==ModifierKeys.Control;
        if(e.Key==Key.F2 && current!=null){e.Handled=true;await Guard(async()=>{var text=LineText.SelectedText.Length>0 ? LineText.SelectedText : LineText.Text;await SaveCurrent();new ResearchWindow(current.Id,Call,text){Owner=this}.ShowDialog();});return;}
        if(e.Key==Key.F8 && Keyboard.Modifiers==ModifierKeys.None)
        { e.Handled=true; await Guard(async()=>{await SaveEditedLine(); NextUncertainLine();}); }
        else if(control && e.Key==Key.Enter)
        { e.Handled=true; await Guard(async()=>{if(LineList.SelectedItem==null) return; await SaveEditedLine(true); NextUncertainLine();}); }
        else if(control && e.Key==Key.S)
        { e.Handled=true; await Guard(async()=>{await SaveCurrent(); Status.Text=T("Зміни збережено.");}); }
        else if(control && e.Key is Key.Add or Key.OemPlus or Key.Subtract or Key.OemMinus or Key.D0 or Key.NumPad0)
        { e.Handled=true; Zoom.Value=e.Key is Key.D0 or Key.NumPad0 ? .65 : Math.Clamp(Zoom.Value+(e.Key is Key.Add or Key.OemPlus ? .2 : -.2),Zoom.Minimum,Zoom.Maximum); CenterSelectedLine(); }
    }
    async Task SmokeShortcuts()
    {
        if(current==null) throw new Exception("No shortcut smoke page");
        NextUncertainLine(); LineText.Text="First corrected"; await SaveEditedLine(); NextUncertainLine();
        if(LineList.SelectedIndex!=1) throw new Exception("Next unverified line failed");
        LineText.Text="Second verified"; await SaveEditedLine(true); NextUncertainLine();
        if(LineList.SelectedIndex!=0) throw new Exception("Verified line was not skipped");
        var details=await Call("details",new(){["id"]=current.Id});
        if(details["lines"]?[0]?["corrected"]?.ToString()!="First corrected" || details["lines"]?[0]?["verified"]?.GetValue<bool>()!=false || details["lines"]?[1]?["verified"]?.GetValue<bool>()!=true) throw new Exception("Line correction persistence failed");
        System.IO.File.WriteAllText(System.IO.Path.Combine(root,"shortcuts-smoke.json"),details.ToJsonString());
    }
}
